"""AgentEvent 的安全详情过滤与并发安全工厂。"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Protocol
from uuid import uuid4

from backend.core.observability.context import TraceContext
from backend.schemas.agent_event import AgentEvent

logger = logging.getLogger("backend.agent.events")


_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "authorization",
    "password",
    "secret",
    "token",
}


def _is_sensitive_key(key: object) -> bool:
    """判断字典键是否代表凭据字段。"""
    normalized = str(key).strip().lower().replace("-", "_")
    return normalized in _SENSITIVE_KEYS or normalized.endswith(
        ("_api_key", "_password", "_secret", "_token")
    )


def sanitize_event_detail(
    value: object,
    *,
    max_string: int = 4000,
    max_items: int = 50,
) -> object:
    """递归移除凭据并限制事件详情体积。

    Args:
        value: 待过滤的任意 JSON 风格值。
        max_string: 单个字符串允许的最大字符数。
        max_items: 单个列表或字典允许保留的最大元素数。

    Returns:
        可安全进入事件和日志的副本。
    """
    if max_string < 0 or max_items < 0:
        raise ValueError("max_string and max_items must be non-negative")
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if isinstance(value, str):
        if len(value) <= max_string:
            return value
        return f"{value[:max_string]}…"
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            if _is_sensitive_key(key):
                continue
            result[str(key)] = sanitize_event_detail(
                item, max_string=max_string, max_items=max_items
            )
        return result
    if isinstance(value, (list, tuple, set, frozenset)):
        return [
            sanitize_event_detail(item, max_string=max_string, max_items=max_items)
            for item in list(value)[:max_items]
        ]
    return sanitize_event_detail(
        str(value), max_string=max_string, max_items=max_items
    )


class EventFactory:
    """为单个 Turn 创建关联一致、sequence 单调的 AgentEvent。"""

    def __init__(self, trace: TraceContext) -> None:
        """初始化工厂并绑定一个不可变 Trace。"""
        self._trace = trace
        self._sequence = 0
        self._lock = asyncio.Lock()

    async def create(
        self,
        *,
        event_type: str,
        stage: str,
        stage_id: str,
        status: str,
        visibility: str,
        sensitivity: str = "normal",
        started_at: datetime | None = None,
        duration_ms: int | None = None,
        summary: str | None = None,
        detail: dict[str, Any] | None = None,
        content: str | None = None,
        code: str | None = None,
        citations: list[dict[str, Any]] | None = None,
    ) -> AgentEvent:
        """并发安全地创建下一个事件。"""
        async with self._lock:
            self._sequence += 1
            sequence = self._sequence

        safe_detail = sanitize_event_detail(detail or {})
        return AgentEvent.model_validate(
            {
                "protocol_version": 2,
                "event_id": f"evt_{uuid4().hex}",
                "request_id": self._trace.request_id,
                "trace_id": self._trace.trace_id,
                "turn_id": self._trace.turn_id,
                "conversation_id": self._trace.conversation_id,
                "agent_id": self._trace.agent_id,
                "sequence": sequence,
                "type": event_type,
                "stage": stage,
                "stage_id": stage_id,
                "status": status,
                "visibility": visibility,
                "sensitivity": sensitivity,
                "started_at": started_at or datetime.now(timezone.utc),
                "duration_ms": duration_ms,
                "summary": summary,
                "detail": safe_detail,
                "content": content,
                "code": code,
                "citations": citations,
            }
        )


class EventSink(Protocol):
    """AgentEvent 异步输出目标协议。"""

    async def emit(self, event: AgentEvent) -> None:
        """接收一个已经校验的事件。"""
        ...


class MemoryEventSink:
    """将事件保存在内存中的测试与聚合 Sink。"""

    def __init__(self) -> None:
        """创建空事件列表。"""
        self.events: list[AgentEvent] = []

    async def emit(self, event: AgentEvent) -> None:
        """按到达顺序保存事件。"""
        self.events.append(event)


class QueueEventSink:
    """将事件推入 asyncio.Queue，供 SSE 消费。"""

    def __init__(self, queue: asyncio.Queue[AgentEvent] | None = None) -> None:
        """使用给定队列或创建新队列。"""
        self.queue = queue or asyncio.Queue()

    async def emit(self, event: AgentEvent) -> None:
        """把事件写入队列。"""
        await self.queue.put(event)


class CompositeEventSink:
    """将事件广播到多个相互隔离的 Sink。"""

    def __init__(self, sinks: list[EventSink]) -> None:
        """保存按调用顺序执行的 Sink。"""
        self._sinks = list(sinks)

    async def emit(self, event: AgentEvent) -> None:
        """逐个广播；单个旁路失败只写 fallback 日志。"""
        for sink in self._sinks:
            try:
                await sink.emit(event)
            except Exception:
                logger.exception(
                    "event sink failed",
                    extra={"trace_id": event.trace_id, "event_id": event.event_id},
                )


class EventPublisher:
    """组合 EventFactory 与 EventSink 的单 Turn 发布器。"""

    def __init__(self, factory: EventFactory, sink: EventSink) -> None:
        """绑定单 Turn 工厂和输出目标。"""
        self.factory = factory
        self.sink = sink

    async def publish(self, **event_fields: Any) -> AgentEvent:
        """创建、校验并发布一个事件。"""
        event = await self.factory.create(**event_fields)
        await self.sink.emit(event)
        return event


__all__ = [
    "CompositeEventSink",
    "EventFactory",
    "EventPublisher",
    "EventSink",
    "MemoryEventSink",
    "QueueEventSink",
    "sanitize_event_detail",
]
