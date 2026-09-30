"""统一管理 Agent 阶段生命周期和事件发布。"""

import asyncio
from datetime import datetime, timezone
from time import perf_counter
from types import TracebackType
from typing import Any, Literal
from uuid import uuid4

from backend.core.observability.context import current_trace
from backend.core.observability.events import (
    EventFactory,
    EventPublisher,
    EventSink,
)
from backend.schemas.agent_event import EventStatus, EventVisibility

FailurePolicy = Literal["degrade", "raise"]


class StageRunner:
    """为一个 Agent 阶段发出配对的开始和终态事件。"""

    def __init__(
        self,
        stage: str,
        *,
        sink: EventSink | EventPublisher,
        stage_id: str | None = None,
        visibility: EventVisibility | str = EventVisibility.DEBUG,
        timeout_ms: int | None = 10_000,
        failure_policy: FailurePolicy = "raise",
    ) -> None:
        """配置阶段身份、输出、超时和失败策略。"""
        self.stage = stage
        self.stage_id = stage_id or f"{stage}.{uuid4().hex[:8]}"
        self.visibility = EventVisibility(visibility)
        self.timeout_ms = timeout_ms
        self.failure_policy = failure_policy
        self._sink_or_publisher = sink
        self._publisher: EventPublisher | None = None
        self._started_at_wall: datetime | None = None
        self._started_at_perf: float | None = None
        self._terminal: dict[str, Any] | None = None
        self._timeout_context: asyncio.Timeout | None = None

    async def __aenter__(self) -> "StageRunner":
        """启动超时范围并发布 stage.started。"""
        if isinstance(self._sink_or_publisher, EventPublisher):
            self._publisher = self._sink_or_publisher
        else:
            trace = current_trace()
            if trace is None:
                raise RuntimeError("StageRunner requires a bound TraceContext")
            self._publisher = EventPublisher(
                EventFactory(trace), self._sink_or_publisher
            )

        if self.timeout_ms is not None:
            self._timeout_context = asyncio.timeout(self.timeout_ms / 1000)
            await self._timeout_context.__aenter__()

        self._started_at_wall = datetime.now(timezone.utc)
        self._started_at_perf = perf_counter()
        await self._publisher.publish(
            event_type="stage.started",
            stage=self.stage,
            stage_id=self.stage_id,
            status=EventStatus.RUNNING,
            visibility=self.visibility,
            started_at=self._started_at_wall,
        )
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        """发布唯一阶段终态，并按策略传播或降级异常。"""
        timed_out = False
        if self._timeout_context is not None:
            try:
                await self._timeout_context.__aexit__(exc_type, exc, traceback)
            except TimeoutError as timeout_error:
                exc_type = TimeoutError
                exc = timeout_error
                traceback = timeout_error.__traceback__
                timed_out = True

        if isinstance(exc, asyncio.CancelledError) and not timed_out:
            await self._emit_terminal(
                event_type="stage.failed",
                status=EventStatus.CANCELLED,
                summary="stage cancelled",
                code="CANCELLED",
            )
            return False

        if exc is not None:
            status = (
                EventStatus.DEGRADED
                if self.failure_policy == "degrade"
                else EventStatus.FAILED
            )
            code = "TIMEOUT" if timed_out else exc.__class__.__name__.upper()
            summary = "stage timed out" if timed_out else str(exc)
            await self._emit_terminal(
                event_type="stage.failed",
                status=status,
                summary=summary,
                code=code,
            )
            return self.failure_policy == "degrade"

        terminal = self._terminal or {
            "event_type": "stage.completed",
            "status": EventStatus.COMPLETED,
            "summary": None,
            "detail": {},
            "code": None,
        }
        await self._emit_terminal(**terminal)
        return False

    async def progress(
        self, *, summary: str | None = None, detail: dict[str, Any] | None = None
    ) -> None:
        """发布非终态阶段进度。"""
        if self._publisher is None or self._started_at_wall is None:
            raise RuntimeError("StageRunner has not been entered")
        await self._publisher.publish(
            event_type="stage.progress",
            stage=self.stage,
            stage_id=self.stage_id,
            status=EventStatus.RUNNING,
            visibility=self.visibility,
            started_at=self._started_at_wall,
            duration_ms=self._duration_ms(),
            summary=summary,
            detail=detail or {},
        )

    def complete(
        self, *, summary: str | None = None, detail: dict[str, Any] | None = None
    ) -> None:
        """将阶段标记为成功完成。"""
        self._set_terminal(
            event_type="stage.completed",
            status=EventStatus.COMPLETED,
            summary=summary,
            detail=detail,
        )

    def skip(
        self,
        *,
        summary: str | None = None,
        detail: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        """将阶段标记为策略跳过。"""
        self._set_terminal(
            event_type="stage.completed",
            status=EventStatus.SKIPPED,
            summary=summary,
            detail=detail,
            code=code,
        )

    def degrade(
        self,
        *,
        summary: str | None = None,
        detail: dict[str, Any] | None = None,
        code: str = "DEGRADED",
    ) -> None:
        """将阶段标记为已降级但不中断 Turn。"""
        self._set_terminal(
            event_type="stage.failed",
            status=EventStatus.DEGRADED,
            summary=summary,
            detail=detail,
            code=code,
        )

    def _set_terminal(
        self,
        *,
        event_type: str,
        status: EventStatus,
        summary: str | None,
        detail: dict[str, Any] | None,
        code: str | None = None,
    ) -> None:
        """保存待退出时发布的唯一显式终态。"""
        if self._terminal is not None:
            raise RuntimeError("stage terminal state already set")
        self._terminal = {
            "event_type": event_type,
            "status": status,
            "summary": summary,
            "detail": detail or {},
            "code": code,
        }

    def _duration_ms(self) -> int:
        """返回阶段开始后的单调时钟耗时。"""
        if self._started_at_perf is None:
            return 0
        return max(0, round((perf_counter() - self._started_at_perf) * 1000))

    async def _emit_terminal(
        self,
        *,
        event_type: str,
        status: EventStatus,
        summary: str | None,
        detail: dict[str, Any] | None = None,
        code: str | None = None,
    ) -> None:
        """发布阶段的最终事件。"""
        if self._publisher is None or self._started_at_wall is None:
            raise RuntimeError("StageRunner has not been entered")
        await self._publisher.publish(
            event_type=event_type,
            stage=self.stage,
            stage_id=self.stage_id,
            status=status,
            visibility=self.visibility,
            started_at=self._started_at_wall,
            duration_ms=self._duration_ms(),
            summary=summary,
            detail=detail or {},
            code=code,
        )


__all__ = ["FailurePolicy", "StageRunner"]
