"""作者：LHF；时间：2026-10-25；作用：操作完成后统一记录完整脱敏输入输出及父子关系。"""

import inspect
import logging
import traceback
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from functools import wraps
from time import perf_counter
from uuid import uuid4

from backend.core.observability.context import current_trace

_operation = ContextVar("trace_operation", default=None)
_model_scope = ContextVar("trace_model_scope", default=None)
logger = logging.getLogger("backend.agent.trace")


def current_operation():
    """获取当前任务的父操作，ContextVar 保证并发调用互不串联。"""
    return _operation.get()


def model_scope():
    """返回当前逻辑模型调用的用途、厂商及重试计数。"""
    return _model_scope.get()


def bind_model_scope(value):
    """绑定模型用途，返回恢复句柄供调用方 finally 使用。"""
    return _model_scope.set(value)


def reset_model_scope(token):
    """恢复上一层模型用途，避免串行请求泄漏元数据。"""
    _model_scope.reset(token)


@contextmanager
def model_call_scope(purpose, provider=None):
    """为一次框架模型调用建立逻辑 ID，内部 SDK 重试共享用途与编号。"""
    token = bind_model_scope(
        {
            "purpose": purpose,
            "provider": provider,
            "logical_call_id": f"llm_{uuid4().hex}",
            "attempt": 0,
        }
    )
    try:
        yield
    finally:
        reset_model_scope(token)


def observe_model_call(function):
    """为直接 LLM 调用标注实际用途，HTTP 重试沿用同一逻辑调用 ID。"""
    signature = inspect.signature(function)

    def begin(args, kwargs):
        """解析调用参数并创建请求局部模型元数据。"""
        values = signature.bind(*args, **kwargs)
        values.apply_defaults()
        return bind_model_scope(
            {
                "purpose": values.arguments.get("purpose", "answer"),
                "provider": values.arguments.get("provider"),
                "logical_call_id": f"llm_{uuid4().hex}",
                "attempt": 0,
            }
        )

    if inspect.isasyncgenfunction(function):

        @wraps(function)
        async def streaming(*args, **kwargs):
            """在流被实际消费时绑定用途，并在关闭时恢复上下文。"""
            token = begin(args, kwargs)
            iterator = function(*args, **kwargs)
            try:
                async for item in iterator:
                    yield item
            finally:
                try:
                    await iterator.aclose()
                finally:
                    reset_model_scope(token)

        return streaming

    @wraps(function)
    async def invoke(*args, **kwargs):
        """非流式调用同样在 finally 恢复用途。"""
        token = begin(args, kwargs)
        try:
            return await function(*args, **kwargs)
        finally:
            reset_model_scope(token)

    return invoke


class Operation:
    """仅写一次终态的操作记录，输入输出保持 JSON 结构，不进行预览裁剪。"""

    def __init__(
        self,
        kind,
        summary,
        *,
        input=None,
        metadata=None,
        operation_id=None,
        parent_id=None,
    ):
        """保存开始时间、链路及父操作标识；构造期间不输出日志。"""
        trace = current_trace()
        parent = current_operation()
        if trace is not None:
            trace.operation_counts[kind] = trace.operation_counts.get(kind, 0) + 1
        self.operation_id = operation_id or f"op_{uuid4().hex}"
        self.parent_id = parent_id or (
            parent.operation_id if parent else (trace.turn_id if trace else None)
        )
        self.kind, self.summary = kind, summary
        self.input, self.output = input, None
        self.metadata = dict(metadata or {})
        self.started_at = datetime.now(UTC).isoformat()
        self.started = perf_counter()
        self.status = "completed"
        self.error = None
        self.finished = False
        self.trace = {
            key: getattr(trace, key, None)
            for key in (
                "request_id",
                "trace_id",
                "turn_id",
                "conversation_id",
                "agent_id",
            )
        }

    def __enter__(self):
        """进入操作作用域，让子工具、模型和检索自动关联父调用。"""
        self._token = _operation.set(self)
        return self

    def __exit__(self, exc_type, error, tb):
        """成功、失败或取消均写一条终态，并原样传播异常。"""
        try:
            self.finish(error=error)
        finally:
            _operation.reset(self._token)
        return False

    def finish(self, *, error=None, status=None):
        """幂等写入终态；异常结果保留调用方已捕获的部分输出。"""
        if self.finished:
            return
        self.finished = True
        if status is not None:
            self.status = status
        if error is not None:
            self.status = "failed" if isinstance(error, Exception) else "cancelled"
            self.error = {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": "".join(traceback.format_exception(error)),
            }
        payload = {
            **self.trace,
            "record_version": 1,
            "event": "operation.completed",
            "operation_id": self.operation_id,
            "parent_id": self.parent_id,
            "event_id": self.operation_id,
            "kind": self.kind,
            "stage": self.kind,
            "stage_id": self.operation_id,
            "summary": self.summary,
            "started_at": self.started_at,
            "ended_at": datetime.now(UTC).isoformat(),
            "duration_ms": round((perf_counter() - self.started) * 1000),
            "status": self.status,
            "input": self.input,
            "output": self.output,
            "metadata": self.metadata,
            "error": self.error,
            "visibility": "debug",
        }
        # 日志旁路失败不能中断模型/工具；标准 handler 仍负责自身 I/O 错误报告。
        try:
            logger.info("operation.completed", extra={"structured_data": payload})
        except Exception:
            logging.getLogger(__name__).exception("写入操作记录失败")
