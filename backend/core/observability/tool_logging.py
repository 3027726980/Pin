"""工具执行边界日志：覆盖异步流式与非流式调用，不改变工具结果。"""
import asyncio
import logging
import time
import traceback
from uuid import uuid4

from langchain.agents.middleware import AgentMiddleware

from backend.core.observability.context import current_trace
from backend.core.observability.events import diagnostic_preview

logger = logging.getLogger("backend.tool.trace")


class ToolLoggingMiddleware(AgentMiddleware):
    """记录每次真实工具执行的输入、返回、异常及耗时。"""

    async def awrap_tool_call(self, request, handler):
        """透传执行；同一次调用的开始和终态共享 execution_id。"""
        call = request.tool_call
        trace = current_trace()
        identity = {
            "execution_id": f"tool_exec_{uuid4().hex}",
            "tool_call_id": call.get("id"), "tool": call.get("name"),
            "request_id": trace.request_id if trace else None,
            "trace_id": trace.trace_id if trace else None,
            "turn_id": trace.turn_id if trace else None,
            "conversation_id": trace.conversation_id if trace else None,
            "agent_id": trace.agent_id if trace else None,
        }

        def write(event, status, level=logging.INFO, **detail):
            """仅写入脱敏限长数据；异常结构化保留错误位置。"""
            logger.log(level, event, extra={"structured_data": {
                **identity, "event": event, "status": status, **detail,
            }})

        started = time.perf_counter()
        write("tool.started", "running", args=diagnostic_preview(call.get("args", {})))
        try:
            result = await handler(request)
        except asyncio.CancelledError:
            write("tool.cancelled", "cancelled", logging.WARNING,
                  duration_ms=round((time.perf_counter() - started) * 1000))
            raise
        except Exception as error:
            write("tool.failed", "failed", logging.ERROR,
                  duration_ms=round((time.perf_counter() - started) * 1000),
                  error_type=type(error).__name__, error=diagnostic_preview(str(error)),
                  traceback=diagnostic_preview(traceback.format_exc(), limit=12000))
            raise
        failed = getattr(result, "status", None) == "error"
        write("tool.failed" if failed else "tool.completed", "degraded" if failed else "completed",
              logging.WARNING if failed else logging.INFO,
              duration_ms=round((time.perf_counter() - started) * 1000),
              result_type=type(result).__name__, is_error=failed,
              **diagnostic_preview(getattr(result, "content", result)))
        return result
