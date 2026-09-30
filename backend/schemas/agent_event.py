"""AgentEvent v2 统一事件协议。

该模块只描述可被 SSE、前端状态机和结构化日志共同消费的安全事件。
任何 ``secret`` 级数据都必须在进入事件总线前被拒绝。
"""

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class EventStatus(StrEnum):
    """Agent 阶段或 Turn 的执行状态。"""

    WAITING = "waiting"
    RUNNING = "running"
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"
    SKIPPED = "skipped"
    CANCELLED = "cancelled"


class EventVisibility(StrEnum):
    """事件可以到达的最宽可见范围。"""

    PUBLIC = "public"
    DEBUG = "debug"
    INTERNAL = "internal"


class EventSensitivity(StrEnum):
    """事件内容的敏感级别。"""

    NORMAL = "normal"
    USER_CONTENT = "user_content"
    SECRET = "secret"


EventType = Literal[
    "turn.started",
    "stage.started",
    "stage.progress",
    "stage.completed",
    "stage.failed",
    "answer.delta",
    "answer.revision_started",
    "citations.completed",
    "turn.completed",
    "turn.failed",
    "turn.cancelled",
]


class AgentEvent(BaseModel):
    """一次 Agent Turn 中可安全序列化的统一事件。"""

    protocol_version: Literal[2] = 2
    event_id: str = Field(..., min_length=1)
    request_id: str = Field(..., min_length=1)
    trace_id: str = Field(..., min_length=1)
    turn_id: str = Field(..., min_length=1)
    conversation_id: str | None = None
    agent_id: str | None = None
    sequence: int = Field(..., ge=1)
    type: EventType
    stage: str = Field(..., min_length=1)
    stage_id: str = Field(..., min_length=1)
    status: EventStatus
    visibility: EventVisibility
    sensitivity: EventSensitivity = EventSensitivity.NORMAL
    started_at: datetime
    duration_ms: int | None = Field(None, ge=0)
    summary: str | None = None
    detail: dict[str, Any] = Field(default_factory=dict)
    content: str | None = None
    code: str | None = None
    citations: list[dict[str, Any]] | None = None

    model_config = {"extra": "forbid"}

    @model_validator(mode="after")
    def validate_safe_typed_payload(self) -> "AgentEvent":
        """拒绝 secret，并校验特定事件的必需载荷。"""
        if self.sensitivity is EventSensitivity.SECRET:
            raise ValueError("secret data must not enter AgentEvent payloads")

        required_fields = {
            "answer.delta": "content",
            "stage.failed": "code",
            "citations.completed": "citations",
        }
        required = required_fields.get(self.type)
        if required is not None and getattr(self, required) is None:
            raise ValueError(f"{self.type} requires {required}")
        return self


TERMINAL_TYPES = frozenset(
    {"turn.completed", "turn.failed", "turn.cancelled"}
)


def is_terminal_event(event: AgentEvent) -> bool:
    """判断事件是否为 Turn 的唯一终态候选。"""
    return event.type in TERMINAL_TYPES


__all__ = [
    "AgentEvent",
    "EventSensitivity",
    "EventStatus",
    "EventType",
    "EventVisibility",
    "TERMINAL_TYPES",
    "is_terminal_event",
]
