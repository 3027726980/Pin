"""AgentEvent 结构化 Trace 日志 Sink。"""

import logging
from typing import Any

from backend.core.observability.metrics import TurnMetrics
from backend.schemas.agent_event import AgentEvent, is_terminal_event


class TraceLogSink:
    """逐事件写入 agent-trace.jsonl，并在 Turn 终态写汇总。"""

    def __init__(
        self,
        *,
        logger: logging.Logger | None = None,
        metrics: TurnMetrics | None = None,
    ) -> None:
        """绑定目标 logger 和可选的统一 TurnMetrics。"""
        self._logger = logger or logging.getLogger("backend.agent.trace")
        self._metrics = metrics
        self._stage_durations: dict[str, int] = {}

    async def emit(self, event: AgentEvent) -> None:
        """写入一个事件；Turn 终态后追加 trace.summary。"""
        if event.duration_ms is not None and event.type.startswith("stage."):
            self._stage_durations[event.stage_id] = event.duration_ms

        payload = event.model_dump(mode="json")
        payload["event"] = payload.pop("type")
        if event.type == "answer.delta":
            payload["content_length"] = len(payload.pop("content") or "")
        if event.type == "citations.completed":
            citations = payload.pop("citations") or []
            payload["citation_count"] = len(citations)
            payload["citation_refs"] = [
                {
                    key: citation.get(key)
                    for key in ("chunk_id", "document_name", "score")
                    if citation.get(key) is not None
                }
                for citation in citations
            ]
        self._write("agent_event", payload)
        if event.visibility.value == "debug" and event.stage in {"tool", "model", "model_output"}:
            target = "backend.tool.trace" if event.stage == "tool" else "backend.llm.metrics"
            logging.getLogger(target).info("execution.detail", extra={"structured_data": payload})

        if is_terminal_event(event):
            self._write("trace_summary", self._summary_payload(event))

    def _summary_payload(self, event: AgentEvent) -> dict[str, Any]:
        """构造一次 Turn 的汇总指标。"""
        metrics = self._metrics
        return {
            "event": "trace.summary",
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
