"""Agent Trace JSONL 的受限查询服务。

只读取日志根目录下合法日期目录，按字节预算流式扫描；损坏行跳过，
返回值再次经过结构化脱敏，避免日志查询成为敏感信息旁路。
"""

from __future__ import annotations

import json
import re
from collections import OrderedDict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable

from backend.core.config import settings
from backend.core.observability.events import sanitize_event_detail

_TRACE_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class TraceQueryError(ValueError):
    """Trace 查询参数或扫描预算不合法。"""


class TraceQueryService:
    """提供有界的 Trace 列表、详情和安全导出。"""

    def __init__(
        self,
        log_dir: str | Path | None = None,
        *,
        max_range_days: int = 31,
        max_scan_bytes: int = 20 * 1024 * 1024,
        index_size: int = 2000,
    ) -> None:
        """初始化日志根目录与查询上限，并只重建当天 summary 索引。"""
        self.log_dir = Path(
            log_dir or getattr(settings.logging, "dir", "logs")
        ).resolve()
        self.max_range_days = max_range_days
        self.max_scan_bytes = max_scan_bytes
        self.index_size = index_size
        self._summaries: OrderedDict[str, dict[str, Any]] = OrderedDict()
        self._rebuild_today_index()

    @staticmethod
    def validate_trace_id(trace_id: str) -> str:
        """校验 trace_id，禁止路径字符和超长输入。"""
        if not _TRACE_ID_RE.fullmatch(trace_id) or ".." in trace_id:
            raise TraceQueryError("非法 trace_id")
        return trace_id

    def parse_range(
        self,
        date_from: str | None,
        date_to: str | None,
    ) -> tuple[date, date]:
        """解析闭区间日期，默认今天，最多 ``max_range_days``。"""
        end = self._parse_date(date_to) if date_to else date.today()
        start = self._parse_date(date_from) if date_from else end
        if start > end:
            raise TraceQueryError("开始日期不能晚于结束日期")
        if (end - start).days + 1 > self.max_range_days:
            raise TraceQueryError(f"日期范围不能超过 {self.max_range_days} 天")
        return start, end

    def list_traces(
        self,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        page: int = 1,
        page_size: int = 20,
        agent_id: str | None = None,
        status: str | None = None,
        model: str | None = None,
    ) -> dict[str, Any]:
        """按过滤条件分页返回 trace.summary，扫描量受全局字节预算限制。"""
        if page < 1 or page_size < 1 or page_size > 100:
            raise TraceQueryError("分页参数超出范围")
        start, end = self.parse_range(date_from, date_to)
        rows = [
            row for row in self._scan(start, end)
            if row.get("event") == "trace.summary"
            and (not agent_id or row.get("agent_id") == agent_id)
            and (not status or row.get("status") == status)
            and (not model or row.get("model") == model)
        ]
        rows.sort(key=lambda row: str(row.get("timestamp", "")), reverse=True)
        offset = (page - 1) * page_size
        return {
            "items": rows[offset:offset + page_size],
            "total": len(rows),
            "page": page,
            "page_size": page_size,
        }

    def get_trace(
        self,
        trace_id: str,
        *,
        date_from: str | None = None,
        date_to: str | None = None,
    ) -> dict[str, Any] | None:
        """返回一个 Trace 的可见事件与 summary；internal 事件不对管理 UI 暴露。"""
        trace_id = self.validate_trace_id(trace_id)
        if date_from is None and date_to is None:
            end = date.today()
            start = end - timedelta(days=self.max_range_days - 1)
        else:
            start, end = self.parse_range(date_from, date_to)
        rows = [
            row for row in self._scan(start, end)
            if row.get("trace_id") == trace_id
            and row.get("visibility") != "internal"
        ]
        if not rows:
            return None
        rows.sort(key=lambda row: (int(row.get("sequence", 10**9)), str(row.get("timestamp", ""))))
        summary = next((row for row in rows if row.get("event") == "trace.summary"), None)
        events = [row for row in rows if row.get("event") != "trace.summary"]
        return {"trace_id": trace_id, "summary": summary, "events": events}

    def export_trace(self, trace_id: str, **kwargs: Any) -> str | None:
        """以安全 JSON 文本导出详情，不返回原始文件内容。"""
        result = self.get_trace(trace_id, **kwargs)
        if result is None:
            return None
        return json.dumps(
            sanitize_event_detail(result),
            ensure_ascii=False,
            indent=2,
            default=str,
        )

    def _rebuild_today_index(self) -> None:
        """启动时仅扫描当天文件，构建有界 summary 索引。"""
        today = date.today()
        try:
            for row in self._scan(today, today):
                if row.get("event") != "trace.summary" or not row.get("trace_id"):
                    continue
                key = str(row["trace_id"])
                self._summaries[key] = row
                self._summaries.move_to_end(key)
                while len(self._summaries) > self.index_size:
                    self._summaries.popitem(last=False)
        except TraceQueryError:
            # 索引只是加速层；超预算时查询仍可显式返回错误，不阻断服务启动。
            self._summaries.clear()

    def _scan(self, start: date, end: date) -> Iterable[dict[str, Any]]:
        """逐行扫描目标日期文件，严格累计已读取字节数。"""
        consumed = 0
        current = start
        while current <= end:
            day_dir = (self.log_dir / current.isoformat()).resolve()
            if day_dir.parent != self.log_dir:
                raise TraceQueryError("非法日志目录")
            if day_dir.is_dir():
                files = sorted(day_dir.glob("agent-trace.jsonl*"))
                for path in files:
                    if not path.is_file() or path.parent.resolve() != day_dir:
                        continue
                    with path.open("rb") as handle:
                        for raw_line in handle:
                            consumed += len(raw_line)
                            if consumed > self.max_scan_bytes:
                                raise TraceQueryError("日志扫描超过最大字节限制")
                            try:
                                value = json.loads(raw_line.decode("utf-8"))
                            except (UnicodeDecodeError, json.JSONDecodeError):
                                continue
                            if isinstance(value, dict):
                                yield sanitize_event_detail(value)
            current += timedelta(days=1)

    @staticmethod
    def _parse_date(value: str) -> date:
        """严格解析 YYYY-MM-DD。"""
        if not _DATE_RE.fullmatch(value):
            raise TraceQueryError("日期格式必须为 YYYY-MM-DD")
        try:
            return datetime.strptime(value, "%Y-%m-%d").date()
        except ValueError as exc:
            raise TraceQueryError("日期无效") from exc


trace_query_service = TraceQueryService()

__all__ = ["TraceQueryError", "TraceQueryService", "trace_query_service"]
