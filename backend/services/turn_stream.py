"""Agent 单一 Turn 事件流、旧 runner 适配与 SSE 序列化。"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from time import perf_counter
from typing import Any

from backend.core.observability.context import TraceContext, bind_trace
from backend.core.observability.events import EventFactory
from backend.core.observability.logger import TraceLogSink
from backend.core.observability.metrics import TurnMetrics
from backend.schemas.agent_event import (
    AgentEvent,
    EventStatus,
    EventVisibility,
)
from backend.core.config import settings
from backend.services.model_policy import TurnBudget, bind_turn_budget


def encode_sse(event: AgentEvent) -> str:
    """把一个 AgentEvent 编码为带 id 的标准 SSE 帧。"""
    payload = event.model_dump(mode="json", exclude_none=True)
    return (
        f"id: {event.event_id}\n"
        f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"
    )


def filter_event_visibility(
    event: AgentEvent, *, public: bool
) -> AgentEvent | None:
    """按 endpoint 权限过滤事件；公开 Widget 只允许 public。"""
    allowed = (
        {EventVisibility.PUBLIC}
        if public
        else {EventVisibility.PUBLIC, EventVisibility.DEBUG}
    )
    return event if event.visibility in allowed else None


def _as_dict_list(value: object) -> list[dict[str, Any]]:
    """把 Citation 模型或字典列表统一转为 JSON 字典。"""
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if isinstance(item, dict):
            result.append(item)
        elif hasattr(item, "model_dump"):
            result.append(item.model_dump(mode="json"))
    return result


async def execute_turn_stream(
    *,
    request_id: str,
    runner: AsyncIterator[dict[str, Any]],
    agent_id: object | None = None,
    conversation_id: object | None = None,
) -> AsyncIterator[AgentEvent]:
    """将内部领域事件转换为唯一终态的 AgentEvent v2 流。

    内部 runner 可以继续使用兼容事件，但不得决定 Turn 终态。该函数是
    ``turn.completed/failed/cancelled`` 的唯一发布者，并始终写安全 Trace。
    """
    turn_started_perf = perf_counter()
    iterator = runner.__aiter__()
    pending: list[dict[str, Any]] = []
    initial_error: BaseException | None = None
    try:
        first = await anext(iterator)
        if first.get("type") == "context":
            conversation_id = first.get("conversation_id") or conversation_id
        else:
            pending.append(first)
    except StopAsyncIteration:
        pass
    except BaseException as error:
        initial_error = error

    trace = TraceContext.new(
        request_id=request_id,
        conversation_id=conversation_id,
        agent_id=agent_id,
    )
    factory = EventFactory(trace)
    metrics = TurnMetrics(started_at=turn_started_perf)
    agent_cfg = getattr(settings, "agent", None)
    budget_cfg = getattr(agent_cfg, "turn_budget", None)
    budget = TurnBudget(
        max_llm_calls=int(getattr(budget_cfg, "max_llm_calls", 8)),
        max_tool_calls=int(getattr(budget_cfg, "max_tool_calls", 8)),
        deadline_ms=int(getattr(budget_cfg, "deadline_ms", 120000)),
    )
    trace_sink = TraceLogSink(metrics=metrics)
    terminal_emitted = False
    started_at = datetime.now(timezone.utc)

    async def make_event(**fields: Any) -> AgentEvent:
        """创建事件并在返回 SSE 前写入 Trace。"""
        event = await factory.create(**fields)
        await trace_sink.emit(event)
        return event

    def finish_metrics() -> None:
        """在终态前同步预算计数并结束 Turn 指标。"""
        metrics.llm_calls = budget.llm_calls_used
        metrics.tool_calls = budget.tool_calls_used
        metrics.finish()

    async with bind_trace(trace), bind_turn_budget(budget):
        metrics.mark_feedback()
        started = await make_event(
            event_type="turn.started",
            stage="request",
            stage_id="request.1",
            status=EventStatus.RUNNING,
            visibility=EventVisibility.PUBLIC,
            started_at=started_at,
            summary="请求已接收",
        )
        yield started

        async def handle_legacy(legacy: dict[str, Any]) -> AgentEvent | None:
            """将一个旧领域事件转换为 v2；done/context 不直接输出。"""
            nonlocal terminal_emitted
            event_type = legacy.get("type")
            if event_type in {"context", "done"}:
                return None
            if terminal_emitted:
                return None
            if event_type == "delta":
                metrics.mark_answer_delta()
                return await make_event(
                    event_type="answer.delta",
                    stage="answer",
                    stage_id="answer.1",
                    status=EventStatus.RUNNING,
                    visibility=EventVisibility.PUBLIC,
                    started_at=started_at,
                    content=str(legacy.get("content", "")),
                )
            if event_type == "answer.revision_started":
                return await make_event(
                    event_type="answer.revision_started",
                    stage="revision",
                    stage_id="revision.1",
                    status=EventStatus.RUNNING,
                    visibility=EventVisibility.PUBLIC,
                    started_at=started_at,
                    summary="正在修订回答",
                )
            if event_type == "citations":
                citations = _as_dict_list(legacy.get("citations"))
                return await make_event(
                    event_type="citations.completed",
                    stage="citation_binding",
                    stage_id="citation_binding.1",
                    status=EventStatus.COMPLETED,
                    visibility=EventVisibility.PUBLIC,
                    started_at=started_at,
                    summary=f"已绑定 {len(citations)} 个来源",
                    detail={"bindings": legacy.get("bindings", [])},
                    citations=citations,
                )
            if event_type == "error":
                finish_metrics()
                terminal_emitted = True
                return await make_event(
                    event_type="turn.failed",
                    stage="request",
                    stage_id="request.1",
                    status=EventStatus.FAILED,
                    visibility=EventVisibility.PUBLIC,
                    started_at=started_at,
                    duration_ms=metrics.total_duration_ms,
                    summary=str(legacy.get("message", "请求失败")),
                    code=str(legacy.get("code", "INTERNAL_ERROR")),
                    detail={"suggestion": legacy.get("suggestion")},
                )
            if event_type == "debug":
                return await make_event(
                    event_type="stage.completed",
                    stage="agent",
                    stage_id="agent.debug",
                    status=EventStatus.COMPLETED,
                    visibility=EventVisibility.DEBUG,
                    started_at=started_at,
                    summary="调试详情已记录",
                    detail=legacy.get("debug") or {},
                )
            if event_type == "stage":
                raw_status = str(legacy.get("status", "running"))
                try:
                    stage_status = EventStatus(raw_status)
                except ValueError:
                    stage_status = EventStatus.RUNNING
                visibility = (EventVisibility.DEBUG
                              if legacy.get("visibility") == "debug"
                              else EventVisibility.PUBLIC)
                return await make_event(
                    event_type=("stage.started" if stage_status is EventStatus.RUNNING
                                else "stage.failed" if stage_status is EventStatus.FAILED
                                else "stage.completed"),
                    stage=str(legacy.get("stage", "agent")),
                    stage_id=str(legacy.get("stage_id", "agent.1")),
                    status=stage_status,
                    visibility=visibility,
                    started_at=started_at,
                    duration_ms=legacy.get("duration_ms"),
                    summary=str(legacy.get("summary", "")),
                    detail=legacy.get("detail") or {},
                    code=(str(legacy.get("code", "STAGE_FAILED"))
                          if stage_status is EventStatus.FAILED else None),
                )
            if event_type in {"intent", "plan", "reflect", "verify"}:
                detail = dict(legacy)
                detail.pop("type", None)
                raw_status = str(legacy.get("status", "completed"))
                try:
                    node_status = EventStatus(raw_status)
                except ValueError:
                    node_status = EventStatus.COMPLETED
                return await make_event(
                    event_type="stage.completed",
                    stage=event_type,
                    stage_id=f"{event_type}.1",
                    status=node_status,
                    visibility=(EventVisibility.PUBLIC
                                if event_type in {"intent", "plan", "verify"}
                                else EventVisibility.DEBUG),
                    started_at=started_at,
                    summary={
                        "intent": "意图识别完成",
                        "plan": "任务规划完成",
                        "reflect": "回答反思完成",
                        "verify": "回答核验完成",
                    }[event_type],
                    duration_ms=legacy.get("duration_ms"),
                    detail=detail,
                )
            return await make_event(
                event_type="stage.progress",
                stage="agent",
                stage_id="agent.1",
                status=EventStatus.RUNNING,
                visibility=EventVisibility.INTERNAL,
                started_at=started_at,
                summary="内部事件",
                detail={"legacy_type": event_type},
            )

        try:
            if initial_error is not None:
                raise initial_error
            for legacy in pending:
                mapped = await handle_legacy(legacy)
                if mapped is not None:
                    yield mapped
            async for legacy in iterator:
                mapped = await handle_legacy(legacy)
                if mapped is not None:
                    yield mapped
        except asyncio.CancelledError:
            if not terminal_emitted:
                finish_metrics()
                terminal_emitted = True
                yield await make_event(
                    event_type="turn.cancelled",
                    stage="request",
                    stage_id="request.1",
                    status=EventStatus.CANCELLED,
                    visibility=EventVisibility.PUBLIC,
                    started_at=started_at,
                    duration_ms=metrics.total_duration_ms,
                    summary="请求已取消",
                    code="CANCELLED",
                )
            raise
        except Exception as error:
            if not terminal_emitted:
                finish_metrics()
                terminal_emitted = True
                status_code = getattr(error, "status_code", None)
                yield await make_event(
                    event_type="turn.failed",
                    stage="request",
                    stage_id="request.1",
                    status=EventStatus.FAILED,
                    visibility=EventVisibility.PUBLIC,
                    started_at=started_at,
                    duration_ms=metrics.total_duration_ms,
                    summary=str(getattr(error, "detail", None) or error),
                    code=str(status_code or "INTERNAL_ERROR"),
                )

        if not terminal_emitted:
            finish_metrics()
            terminal_emitted = True
            yield await make_event(
                event_type="turn.completed",
                stage="request",
                stage_id="request.1",
                status=EventStatus.COMPLETED,
                visibility=EventVisibility.PUBLIC,
                started_at=started_at,
                duration_ms=metrics.total_duration_ms,
                summary="请求处理完成",
            )


__all__ = [
    "encode_sse",
    "execute_turn_stream",
    "filter_event_visibility",
]
