"""基于 ContextVar 的单次 Agent Turn 链路上下文。"""

from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import AsyncIterator
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class TraceContext:
    """一次 Agent Turn 的稳定关联标识。"""

    request_id: str
    trace_id: str
    turn_id: str
    conversation_id: str | None = None
    agent_id: str | None = None
    # 作者：LHF；2026-10-25；同一 Turn 的异步子任务共享实际操作计数，区别于预算额度。
    operation_counts: dict[str, int] = field(default_factory=dict, compare=False, repr=False)

    @classmethod
    def new(
        cls,
        *,
        request_id: str,
        conversation_id: object | None = None,
        agent_id: object | None = None,
    ) -> "TraceContext":
        """为一个新 Turn 创建 Trace 上下文。"""
        return cls(
            request_id=request_id,
            trace_id=f"tr_{uuid4().hex}",
            turn_id=f"turn_{uuid4().hex}",
            conversation_id=(
                str(conversation_id) if conversation_id is not None else None
            ),
            agent_id=str(agent_id) if agent_id is not None else None,
        )


_CURRENT_TRACE: ContextVar[TraceContext | None] = ContextVar(
    "agent_trace_context", default=None
)


def current_trace() -> TraceContext | None:
    """返回当前异步上下文绑定的 Trace，没有绑定时返回 None。"""
    return _CURRENT_TRACE.get()


@asynccontextmanager
async def bind_trace(trace: TraceContext) -> AsyncIterator[TraceContext]:
    """在当前异步上下文绑定 Trace，并保证退出时恢复旧值。"""
    token = _CURRENT_TRACE.set(trace)
    try:
        yield trace
    finally:
        _CURRENT_TRACE.reset(token)


__all__ = ["TraceContext", "bind_trace", "current_trace"]
