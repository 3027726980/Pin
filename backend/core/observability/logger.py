# 作者：LHF；时间：2026-10-25；作用：实时事件仅聚合，整轮结束后写完整请求记录。
"""AgentEvent 结构化 Trace 日志 Sink。"""

import logging
from typing import Any
from datetime import datetime, timezone

from backend.core.observability.metrics import TurnMetrics
from backend.schemas.agent_event import AgentEvent, is_terminal_event


class TraceLogSink:
    """作者：LHF；2026-10-25；实时事件仅聚合，Turn 结束后写唯一完整请求记录。"""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        metrics: TurnMetrics | None = None,
        request_input: dict | None = None,
    ) -> None:
        """绑定目标 logger 和可选的统一 TurnMetrics。"""
        self._logger = logger or logging.getLogger("backend.agent.trace")
        self._metrics = metrics
        self._stage_durations: dict[str, int] = {}
        self._request_input = request_input or {}
        self._answer_parts: list[str] = []
        self._citations: list = []
        self._bindings: list = []
        self._request_started_at = None
        self._terminal_written = False
        self._raw_citations = False

    def capture_citations(self, citations, bindings):
        """保存 SSE 安全裁剪前的完整引用，只用于终态日志。"""
        self._citations, self._bindings = citations, bindings
        self._raw_citations = True

    def capture_final_answer(self, answer):
        """终态写入前以领域层清理后的最终答案替换临时增量缓存。"""
        self._answer_parts[:] = [answer]

    async def emit(self, event: AgentEvent) -> None:
        """仅聚合实时事件的数据，在 Turn 终态写完整请求汇总。"""
        # 实时事件继续发给客户端；持久层仅收集数据并在整轮终态写一次请求记录。
        if event.duration_ms is not None and event.type.startswith("stage."):
            self._stage_durations[event.stage_id] = event.duration_ms
        if event.type == "turn.started":
            self._request_started_at = event.started_at.isoformat()
        elif event.type == "answer.revision_started":
            self._answer_parts.clear()
        elif event.type == "answer.delta":
            self._answer_parts.append(event.content or "")
        elif event.type == "citations.completed" and not self._raw_citations:
            self._citations = event.citations or []
            self._bindings = event.detail.get("bindings", [])
        if is_terminal_event(event) and not self._terminal_written:
            self._terminal_written = True
            self._write("trace_summary", self._summary_payload(event))

    def _summary_payload(self, event: AgentEvent) -> dict[str, Any]:
        """构造一次 Turn 的汇总指标。"""
        metrics = self._metrics
        return {
            "event": "trace.summary", "record_version": 1, "kind": "request",
            "operation_id": event.turn_id, "event_id": event.turn_id, "parent_id": None,
            "summary": "请求处理完成" if event.status.value == "completed" else "请求处理结束",
            "started_at": self._request_started_at or event.started_at.isoformat(),
            "ended_at": datetime.now(timezone.utc).isoformat(), "visibility": "debug",
            "duration_ms": metrics.total_duration_ms if metrics else event.duration_ms,
            "input": self._request_input,
            "output": {"answer": "".join(self._answer_parts), "citations": self._citations,
                       "citation_bindings": self._bindings},
            "metadata": {"stage_durations": dict(self._stage_durations),
                         "llm_calls": metrics.llm_calls if metrics else None,
                         "tool_calls": metrics.tool_calls if metrics else None},
            "error": {"code": event.code, "message": event.summary} if event.status.value != "completed" else None,
            "request_id": event.request_id,
            "trace_id": event.trace_id,
            "turn_id": event.turn_id,
            "conversation_id": event.conversation_id,
            "agent_id": event.agent_id,
            "status": event.status.value,
            "feedback_latency_ms": (
                metrics.feedback_latency_ms if metrics is not None else None
            ),
            "answer_first_token_ms": (
                metrics.answer_first_token_ms if metrics is not None else None
            ),
            "total_duration_ms": (
                metrics.total_duration_ms
                if metrics is not None
                else event.duration_ms
            ),
            "queue_wait_ms": metrics.queue_wait_ms if metrics is not None else 0,
            "llm_calls": metrics.llm_calls if metrics is not None else 0,
            "tool_calls": metrics.tool_calls if metrics is not None else 0,
            "stage_durations": dict(self._stage_durations),
        }

    def _write(self, message: str, payload: dict[str, Any]) -> None:
        """使用 LogRecord extra 传递结构化数据。"""
        self._logger.info(message, extra={"structured_data": payload})


__all__ = ["TraceLogSink"]
