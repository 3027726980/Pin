"""RAG 专用 Agent 的每轮首次检索约束。"""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import HumanMessage, ToolMessage


class RagFirstMiddleware(AgentMiddleware):
    """仅在本轮尚未收到 RAG 工具结果时强制工具选择，不直接执行检索。"""

    async def awrap_model_call(self, request, handler):
        """依据当前轮消息选择 rag，工具结果返回后恢复模型自主生成。"""
        retrieved = False
        for message in reversed(request.messages):
            if isinstance(message, HumanMessage):
                break
            if isinstance(message, ToolMessage) and message.name == "rag":
                retrieved = True
                break
        if not retrieved:
            request = request.override(tool_choice={
                "type": "function", "function": {"name": "rag"}})
        return await handler(request)
