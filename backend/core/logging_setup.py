"""日志体系初始化：dictConfig 风格 + 日期目录 + 模板文件名 + 分文件 + 轮转(-1) + 控制台彩色 + 脱敏 + 定时清理 + SQL 监听

设计要点：
- 全部走标准 logging（SQLAlchemy/uvicorn/langchain 的日志统一接管）
- 文件：logs/YYYY-MM-DD/{{date}}-{{module}}.log（模板可配，Windows 非法字符清洗）
- 轮转：backup_count=-1 保留全部（InfiniteRotatingFileHandler，O(1) 滚动）
- 脱敏：规则来自 system_settings 缓存（logging.redact_rules），emit 前统一过滤
- 清理：每天按 config time 删除超期日期目录（后台任务 + 启动补跑）
- SQL：事件监听记录语句（截断 200 字符）/参数/耗时 → sql.log
"""
import asyncio
import copy
import json
import logging
import logging.handlers
import os
import re
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path

from backend.core.config import settings

logger = logging.getLogger(__name__)


class ConsoleEventFilter(logging.Filter):
    """控制台忽略高频增量；完整事件仍交给文件 handler。"""

    def filter(self, record: logging.LogRecord) -> bool:
        """保留故障及阶段边界，过滤正常进度与重复 Turn 终态。"""
        payload = getattr(record, "structured_data", None)
        if record.name != "backend.agent.trace" or not isinstance(payload, dict):
            return True
        if payload.get("status") in {"failed", "degraded", "cancelled"}:
            return True
        return payload.get("event") not in {
            "answer.delta", "stage.progress", "turn.completed",
        } and payload.get("visibility") not in {"debug", "internal"}


class ConsoleEventFormatter(logging.Formatter):
    """为结构化事件生成简短摘要，保留彩色格式且不修改原始 LogRecord。"""

    def __init__(self, delegate: logging.Formatter):
        """绑定普通或彩色 formatter。"""
        super().__init__()
        self.delegate = delegate

    def format(self, record: logging.LogRecord) -> str:
        """仅显示关联标识和执行指标，不输出正文、工具参数或凭据。"""
        payload = getattr(record, "structured_data", None)
        if not isinstance(payload, dict):
            return self.delegate.format(record)

        def value(key: str, default="-") -> str:
            """限制字段长度并转义换行，避免日志注入。"""
            raw = payload.get(key)
            return str(default if raw is None else raw).replace("\r", "\\r").replace("\n", "\\n")[:200]

        if record.name == "backend.http":
            message = (f"{value('method')} {value('path')} status={value('status')} "
                       f"duration={value('duration_ms')}ms request={value('request_id')}")
        elif record.name == "backend.agent.trace":
            if payload.get("event") == "trace.summary":
                message = (f"Turn 汇总 status={value('status')} total={value('total_duration_ms')}ms "
                           f"first_answer={value('answer_first_token_ms')}ms "
                           f"llm_calls={value('llm_calls')} tool_calls={value('tool_calls')}")
            else:
                message = (f"{value('event')} stage={value('stage_id')} "
                           f"status={value('status')} duration={value('duration_ms')}ms")
                if payload.get("code"):
                    message += f" code={value('code')}"
            message += f" trace={value('trace_id')}"
        elif record.name == "backend.tool.trace" and str(payload.get("event", "")).startswith("tool."):
            message = (f"{value('event')} tool={value('tool')} call={value('tool_call_id')} "
                       f"status={value('status')} duration={value('duration_ms')}ms trace={value('trace_id')}")
            if payload.get("error_type"):
                message += f" error_type={value('error_type')}"
        else:
            return self.delegate.format(record)
        console_record = copy.copy(record)
        console_record.msg = message
        console_record.args = ()
        return self.delegate.format(console_record)


class TraceJsonFormatter(logging.Formatter):
    """把 ``record.structured_data`` 直接输出为单行安全 JSON。"""

    def format(self, record: logging.LogRecord) -> str:
        """序列化结构化字段，并统一补充时间、事件名与日志来源。"""
        from backend.core.observability.events import sanitize_event_detail

        raw = getattr(record, "structured_data", None)
        if isinstance(raw, dict):
            payload = dict(raw)
        else:
            payload = {"message": record.getMessage()}
        payload.setdefault("event", record.getMessage())
        payload.setdefault(
            "timestamp",
            datetime.fromtimestamp(record.created, timezone.utc).isoformat(),
        )
        payload.setdefault("level", record.levelname.lower())
        payload.setdefault("logger", record.name)
        safe_payload = sanitize_event_detail(payload)
        return json.dumps(
            safe_payload,
            ensure_ascii=False,
            separators=(",", ":"),
            default=str,
        )

# 模块短名 → 分文件后缀
_FILE_MODULES = {
    "backend.llm": "llm",
    "sqlalchemy.engine": "sql",
}

_STRUCTURED_FILES = {
    "backend.http": "access.jsonl",
    "backend.agent.trace": "agent-trace.jsonl",
    "backend.llm.metrics": "llm.jsonl",
    "backend.tool.trace": "tool.jsonl",
}


def _sanitize_filename(name: str) -> str:
    """Windows 非法字符清洗（: \\ / * ? \" < > | → -）"""
    return re.sub(r'[\\/:*?"<>|]', "-", name)


def _current_date_text() -> str:
    """返回当前本地日期，独立函数便于跨日轮转测试。"""
    return datetime.now().strftime("%Y-%m-%d")


def _render_template(module_short: str) -> str:
    """渲染文件名模板：{{date}} / {{module}}"""
    tpl = getattr(settings.logging, "filename_template", "{{date}}-{{module}}.log")
    return _sanitize_filename(
        tpl.replace("{{date}}", _current_date_text())
           .replace("{{module}}", module_short))


def _today_dir() -> Path:
    base = Path(getattr(settings.logging, "dir", "logs"))
    return base / _current_date_text()


class InfiniteRotatingFileHandler(logging.handlers.RotatingFileHandler):
    """backupCount=-1：保留全部滚动备份（编号递增，不做批量平移、不删除旧备份）"""

    def doRollover(self) -> None:
        if self.stream:
            self.stream.close()
            self.stream = None
        if self.backupCount == -1:
            # 找当前最大编号 → 新备份 = max+1（O(1)，零平移零删除）
            base = os.path.basename(self.baseFilename)
            d = os.path.dirname(self.baseFilename) or "."
            nums = []
            for f in os.listdir(d):
                m = re.match(re.escape(base) + r"\.(\d+)$", f)
                if m:
                    nums.append(int(m.group(1)))
            nxt = (max(nums) + 1) if nums else 1
            self.rotate(self.baseFilename, f"{self.baseFilename}.{nxt}")
        elif self.backupCount > 0:
            super().doRollover()
        # backupCount == 0：截断重写（不保留备份）
        if not self.delay:
            self.stream = self._open()


class DailyDirectoryRotatingFileHandler(InfiniteRotatingFileHandler):
    """写入前检查日期，并把文件句柄切换到当天目录。"""

    def __init__(
        self,
        module_short: str,
        max_bytes: int,
        backup_count: int,
        filename: str | None = None,
    ):
        self.module_short = module_short
        self.filename = filename
        self.active_date = _current_date_text()
        _today_dir().mkdir(parents=True, exist_ok=True)
        super().__init__(
            str(_today_dir() / self._render_filename()),
            maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8")

    def _render_filename(self) -> str:
        """返回固定文件名或旧版模板文件名。"""
        if self.filename is not None:
            return _sanitize_filename(self.filename)
        return _render_template(self.module_short)

    def emit(self, record: logging.LogRecord) -> None:
        current_date = _current_date_text()
        if current_date != self.active_date:
            if self.stream:
                self.stream.close()
                self.stream = None
            target_dir = Path(getattr(settings.logging, "dir", "logs")) / current_date
            target_dir.mkdir(parents=True, exist_ok=True)
            self.baseFilename = os.path.abspath(
                str(target_dir / self._render_filename()))
            self.active_date = current_date
            if not self.delay:
                self.stream = self._open()
        super().emit(record)


class RedactFilter(logging.Filter):
    """脱敏 Filter：按规则对 record.getMessage() 统一掩码（emit 前，全部 handler 生效）

    规则类型：
      - field_name：匹配字段名（api_key/token/password 等），**连字段值一起掩码**（"password":"admin123" → "password":"******"）
      - value_pattern：匹配值模式（sk-/pin_/Bearer 等），整体掩码
    """

    def __init__(self, rules: dict | None = None):
        super().__init__()
        self._compiled: list[tuple[re.Pattern, str, bool]] = []
        self._enabled = True
        self.reload(rules)

    def reload(self, rules: dict | None) -> None:
        """根据 system_settings 规则重建（修改后调用，立即生效）"""
        rules = rules or {}
        self._enabled = bool(rules.get("enabled", True))
        compiled: list[tuple[re.Pattern, str, bool]] = []
        for r in rules.get("rules", []):
            try:
                if r.get("type") == "field_name":
                    # 字段名 + 其值（支持 key=value 与 JSON "key":"value" 两种形态）
                    # group(1)=字段名+分隔符（含引号），group(2)=字段值
                    pat = re.compile(
                        r'("?(?:' + r["pattern"] + r')"?\s*[:=]\s*"?)([^",}\s]+)')
                    compiled.append((pat, r.get("mask", "keep_4_4"), True))
                else:
                    compiled.append(
                        (re.compile(r["pattern"]), r.get("mask", "keep_4_4"), False))
            except re.error:
                continue
        # 执行顺序：value_pattern 先于 field_name——
        # field_name 掩码后的残留（如 sk-3***5678 中的 sk-3）可能被 value_pattern 二次匹配
        # （value_pattern 掩码对已掩码值幂等，field_name 掩码亦然，顺序正确则无残留问题）
        compiled.sort(key=lambda x: x[2])
        self._compiled = compiled

    @staticmethod
    def _mask(value: str, mask: str) -> str:
        # 幂等：已掩码值（含 ***）不再触发短值全掩，保持原格式
        if mask == "full_mask" or (len(value) < 12 and "***" not in value):
            return "******"
        keep = 3 if mask == "keep_3_3" else 4
        return f"{value[:keep]}***{value[-keep:]}"

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._enabled:
            return True
        msg = record.getMessage()
        changed = False
        for pattern, mask, is_field in self._compiled:
            if is_field:
                # 字段名保留原文，值掩码（"password":"admin123" → "password":"******"）
                def repl(m: re.Match, _mask: str = mask) -> str:
                    nonlocal changed
                    changed = True
                    return m.group(1) + self._mask(m.group(2), _mask)
            else:
                def repl(m: re.Match, _mask: str = mask) -> str:
                    nonlocal changed
                    changed = True
                    return self._mask(m.group(0), _mask)
            msg = pattern.sub(repl, msg)
        if changed:
            record.msg = msg
            record.args = ()
        return True


def _build_file_handler(
    module_short: str,
    level: str,
    *,
    filename: str | None = None,
) -> logging.Handler:
    """按 config 构造文件 handler（含轮转 -1 支持）"""
    rot = getattr(settings.logging, "rotation", None)
    max_bytes = (getattr(rot, "max_bytes_mb", 10) or 10) * 1024 * 1024
    backup = getattr(rot, "backup_count", -1) if rot else -1
    h: logging.Handler = DailyDirectoryRotatingFileHandler(
        module_short, max_bytes, backup, filename=filename)
    h.setLevel(getattr(logging, level))
    return h


def _register_sql_listener() -> None:
    """SQLAlchemy 事件监听：语句（截断 200 字符）/参数/耗时 → sqlalchemy.engine（sql.log）"""
    from sqlalchemy import event
    from sqlalchemy.engine import Engine

    sql_logger = logging.getLogger("sqlalchemy.engine")

    @event.listens_for(Engine, "before_cursor_execute")
    def _before(conn, cursor, statement, parameters, context, executemany):
        conn.info.setdefault("_query_time", []).append(time.perf_counter())

    @event.listens_for(Engine, "after_cursor_execute")
    def _after(conn, cursor, statement, parameters, context, executemany):
        times = conn.info.setdefault("_query_time", [])
        if times:
            dur = (time.perf_counter() - times.pop()) * 1000
            lvl = logging.INFO if dur < 100 else logging.WARNING
            sql_logger.log(
                lvl, "[SQL] %.0fms %s params=%s", dur, statement[:200],
                str(parameters)[:200] if parameters else "")


def setup_logging() -> None:
    """初始化日志体系（lifespan 调用一次）"""
    lg = settings.logging
    base_level = getattr(lg, "level", "INFO")
    _today_dir().mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    root.setLevel(base_level)
    # 清掉默认 handler（避免重复）
    for h in list(root.handlers):
        root.removeHandler(h)

    _file_fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S")

    # 总日志（app.log）
    app_handler = _build_file_handler("app", base_level)
    app_handler.setFormatter(_file_fmt)
    root.addHandler(app_handler)

    # WARNING/ERROR 独立文件，便于不扫描 app.log 即可定位故障。
    error_handler = _build_file_handler(
        "error", "WARNING", filename="error.log"
    )
    error_handler.setFormatter(_file_fmt)
    root.addHandler(error_handler)

    # 控制台（分模块级别已由 logger 层控制；此处仅总开关 + 颜色）
    console_cfg = getattr(lg, "console", None)
    if getattr(console_cfg, "enabled", True):
        use_colors = getattr(console_cfg, "colors", False)
        if use_colors:
            import colorlog
            ch = colorlog.StreamHandler()
            ch.setFormatter(colorlog.ColoredFormatter(
                "%(log_color)s%(levelname)-7s | %(name)s | %(message)s",
                datefmt="%H:%M:%S",
                log_colors={"DEBUG": "white", "INFO": "green",
                            "WARNING": "yellow", "ERROR": "red",
                            "CRITICAL": "red,bg_white"}))
        else:
            ch = logging.StreamHandler()
            ch.setFormatter(logging.Formatter(
                "%(levelname)-7s | %(name)s | %(message)s"))
        ch.setFormatter(ConsoleEventFormatter(ch.formatter))
        ch.addFilter(ConsoleEventFilter())
        # 分模块控制台开关（modules 中为 false 的模块不上控制台，文件照写）
        modules_ns = getattr(console_cfg, "modules", None)
        off_modules = [m for m, v in vars(modules_ns).items() if not v] \
            if modules_ns is not None else []
        if off_modules:
            class _ConsoleFilter(logging.Filter):
                def filter(self, record):
                    return not any(
                        record.name == m or record.name.startswith(m + ".")
                        for m in off_modules)
            ch.addFilter(_ConsoleFilter())
        root.addHandler(ch)

    # 模块初始级别（也是动态切换的还原基准）
    levels_ns = getattr(lg, "levels", None)
    module_levels: dict = vars(levels_ns) if levels_ns is not None else {}
    for mod, lv in module_levels.items():
        logging.getLogger(mod).setLevel(getattr(logging, lv))

    # 分文件 handler（额外一份，同时保留 propagate 进总日志）
    sep_ns = getattr(lg, "separate_files", None)
    separate: dict = vars(sep_ns) if sep_ns is not None else {}
    for mod, short in _FILE_MODULES.items():
        if separate.get(short, False):
            fh = _build_file_handler(short, module_levels.get(mod, base_level))
            fh.setFormatter(_file_fmt)
            logging.getLogger(mod).addHandler(fh)

    # 结构化日志使用固定 JSONL 文件名。重复初始化时只移除本模块管理的
    # handler，不干扰测试或宿主进程自行挂载的 handler。
    json_formatter = TraceJsonFormatter()
    for logger_name, filename in _STRUCTURED_FILES.items():
        target_logger = logging.getLogger(logger_name)
        for old_handler in list(target_logger.handlers):
            if getattr(old_handler, "_pin_structured_handler", False):
                target_logger.removeHandler(old_handler)
                old_handler.close()
        structured_handler = _build_file_handler(
            filename.removesuffix(".jsonl"),
            module_levels.get(logger_name, base_level),
            filename=filename,
        )
        structured_handler.setFormatter(json_formatter)
        structured_handler._pin_structured_handler = True
        target_logger.addHandler(structured_handler)
        target_logger.setLevel(
            getattr(logging, module_levels.get(logger_name, base_level))
        )

    _register_sql_listener()


async def start_cleanup_task() -> asyncio.Task:
    """启动定时清理任务：每天 config time 删除超期日期目录；启动补跑一次"""
    cl = getattr(settings.logging, "cleanup", None)
    base = Path(getattr(settings.logging, "dir", "logs"))
    if not cl or not getattr(cl, "enabled", False):
        return asyncio.create_task(asyncio.sleep(0))  # no-op

    retention = int(getattr(cl, "retention_days", 30))

    async def _clean_once() -> None:
        if not base.exists():
            return
        cutoff = time.time() - retention * 86400
        for d in base.iterdir():
            if not d.is_dir():
                continue
            try:
                dts = datetime.strptime(d.name, "%Y-%m-%d").timestamp()
            except ValueError:
                continue
            if dts < cutoff:
                shutil.rmtree(d, ignore_errors=True)
                logger.info("清理过期日志目录: %s", d)

    await _clean_once()

    async def _loop() -> None:
        while True:
            now = datetime.now()
            try:
                hh, mm = (getattr(cl, "time", "03:30") or "03:30").split(":")
                target = now.replace(hour=int(hh), minute=int(mm), second=0, microsecond=0)
            except ValueError:
                target = now.replace(hour=3, minute=30, second=0, microsecond=0)
            if target <= now:
                target = target.replace(day=target.day + 1)
            await asyncio.sleep((target - now).total_seconds())
            await _clean_once()

    return asyncio.create_task(_loop())
