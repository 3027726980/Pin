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
import logging
import logging.handlers
import os
import re
import shutil
import time
from datetime import datetime
from pathlib import Path

from backend.core.config import settings

logger = logging.getLogger(__name__)

# 模块短名 → 分文件后缀
_FILE_MODULES = {
    "backend.llm": "llm",
    "backend.http": "http",
    "sqlalchemy.engine": "sql",
}


def _sanitize_filename(name: str) -> str:
    """Windows 非法字符清洗（: \\ / * ? \" < > | → -）"""
    return re.sub(r'[\\/:*?"<>|]', "-", name)


def _render_template(module_short: str) -> str:
    """渲染文件名模板：{{date}} / {{module}}"""
    tpl = getattr(settings.logging, "filename_template", "{{date}}-{{module}}.log")
    return _sanitize_filename(
        tpl.replace("{{date}}", datetime.now().strftime("%Y-%m-%d"))
           .replace("{{module}}", module_short))


def _today_dir() -> Path:
    base = Path(getattr(settings.logging, "dir", "logs"))
    return base / datetime.now().strftime("%Y-%m-%d")


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


class RedactFilter(logging.Filter):
    """脱敏 Filter：按规则对 record.getMessage() 统一掩码（emit 前，全部 handler 生效）"""

    def __init__(self, rules: dict | None = None):
        super().__init__()
        self._compiled: list[tuple[re.Pattern, str]] = []
        self._enabled = True
        self.reload(rules)

    def reload(self, rules: dict | None) -> None:
        """根据 system_settings 规则重建（修改后调用，立即生效）"""
        rules = rules or {}
        self._enabled = bool(rules.get("enabled", True))
        self._compiled = []
        for r in rules.get("rules", []):
            try:
                self._compiled.append((re.compile(r["pattern"]), r.get("mask", "keep_4_4")))
            except re.error:
                continue

    @staticmethod
    def _mask(value: str, mask: str) -> str:
        if mask == "full_mask" or len(value) < 12:
            return "******"
        return f"{value[:4]}***{value[-4:]}"

    def filter(self, record: logging.LogRecord) -> bool:
        if not self._enabled:
            return True
        msg = record.getMessage()
        changed = False
        for pattern, mask in self._compiled:
            def repl(m: re.Match, _mask: str = mask) -> str:
                nonlocal changed
                changed = True
                return self._mask(m.group(0), _mask)
            msg = pattern.sub(repl, msg)
        if changed:
            record.msg = msg
            record.args = ()
        return True


def _build_file_handler(module_short: str, level: str) -> logging.Handler:
    """按 config 构造文件 handler（含轮转 -1 支持）"""
    rot = getattr(settings.logging, "rotation", None)
    max_bytes = (getattr(rot, "max_bytes_mb", 10) or 10) * 1024 * 1024
    backup = getattr(rot, "backup_count", -1) if rot else -1
    _today_dir().mkdir(parents=True, exist_ok=True)
    if backup == -1:
        h: logging.Handler = InfiniteRotatingFileHandler(
            str(_today_dir() / _render_template(module_short)),
            maxBytes=max_bytes, backupCount=-1, encoding="utf-8")
    else:
        h = logging.handlers.RotatingFileHandler(
            str(_today_dir() / _render_template(module_short)),
            maxBytes=max_bytes, backupCount=backup, encoding="utf-8")
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
