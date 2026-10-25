"""作者：LHF；时间：2026-10-25；作用：工具完成后一次记录参数、完整结果和异常。"""

import json

from langchain.agents.middleware import AgentMiddleware

from backend.core.observability.operations import Operation, model_call_scope


class ToolLoggingMiddleware(AgentMiddleware):
    """为真实工具执行建立父操作，子模型和检索自动归属此工具。"""

    async def awrap_model_call(self, request, handler):
        """为一次 Agent 模型请求及其 SDK 重试建立共同逻辑调用编号。"""
        with model_call_scope("answer"):
            return await handler(request)

    async def awrap_tool_call(self, request, handler):
        """透传工具执行，结束时写一条记录，不额外调用或重试工具。"""
        call = request.tool_call
        from backend.services.model_policy import current_turn_budget
        budget = current_turn_budget()
        if budget is not None:
            budget.acquire_tool()
        with Operation(
            "tool",
            f"工具调用 · {call.get('name')}",
            input=call.get("args", {}),
            metadata={"tool": call.get("name"), "tool_call_id": call.get("id")},
        ) as operation:
            result = await handler(request)
            content = getattr(result, "content", result)
            if isinstance(content, str):
                try:
                    content = json.loads(content)
                except ValueError:
                    pass
            operation.output = content
            if (
                getattr(result, "status", None) == "error"
                or isinstance(content, dict)
                and "error" in content
            ):
                operation.status = "degraded"
                operation.error = {"type": "ToolError", "message": content}
            return result
