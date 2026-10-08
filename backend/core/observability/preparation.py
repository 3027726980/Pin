"""Agent 准备阶段耗时：进程标识、Trace 关联及可选的实时事件回调。"""
import logging
import os
import time
from contextlib import contextmanager
from contextvars import ContextVar

from backend.core.observability.context import current_trace
from backend.core.observability.events import diagnostic_preview

_sink = ContextVar("preparation_event_sink", default=None)
logger = logging.getLogger("backend.agent.preparation")


@contextmanager
def bind_preparation_sink(sink):
    """为当前执行绑定准备阶段事件，退出后恢复。"""
    token = _sink.set(sink)
    try:
        yield
    finally:
        _sink.reset(token)


@contextmanager
def preparation_stage(name: str, summary: str, **detail):
    """记录同步或异步代码块耗时，异常时记录失败并原样抛出。"""
    started = time.perf_counter()
    trace = current_trace()

    def emit(status, **extra):
        """发送同 ID 的阶段事件并写结构化关联日志。"""
        event = {"type": "stage", "stage": "preparation", "stage_id": f"preparation.{name}",
                 "status": status, "visibility": "debug", "summary": summary,
                 "duration_ms": None if status == "running" else round((time.perf_counter() - started) * 1000),
                 "detail": {"pid": os.getpid(), **detail, **extra}}
        if status == "failed":
            event["code"] = "AGENT_PREPARATION_FAILED"
        logger.log(logging.ERROR if status == "failed" else logging.INFO,
                   "preparation.%s %s duration_ms=%s pid=%s trace=%s detail=%s",
                   name, status, event["duration_ms"], os.getpid(), trace.trace_id if trace else "-", event["detail"])
        sink = _sink.get()
        if sink is not None:
            sink(event)

    emit("running")
    try:
        yield
    except Exception as error:
        emit("failed", error_type=type(error).__name__, **diagnostic_preview(str(error)))
        raise
    else:
        emit("completed")
