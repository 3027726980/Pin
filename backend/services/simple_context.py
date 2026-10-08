"""轻量 Agent 的临时模型上下文投影，不修改持久化消息。"""
from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage

from backend.core.config import settings


class SimpleContextMiddleware(AgentMiddleware):
    """过滤工具协议消息、限制历史并注入最近工具资料，原始状态由框架保存。"""

    async def awrap_model_call(self, request, handler):
        """只覆盖本次模型请求，返回模型响应供 Agent 自动生成 checkpoint。"""
        history = []
        residual = ""
        for message in request.messages[:-1]:
            if isinstance(message, ToolMessage):
                if message.status != "error":
                    residual = message.text
            elif isinstance(message, HumanMessage):
                history.append(message)
            elif isinstance(message, AIMessage) and not message.tool_calls:
                history.append(message)
        limit = settings.intent.simple_history_limit
        if limit > 0:
            history = history[-limit:]
        current = request.messages[-1]
        system = request.system_message
        max_chars = settings.intent.simple_context_max_chars
        if residual and max_chars > 0:
            current = HumanMessage(content=(
                f"以下是历史检索过的资料：\n{residual[:max_chars]}"
                f"\n\n当前问题：{current.text}"))
            system = SystemMessage(content=(
                (system.text if system else "")
                + "\n\n注意：参考资料可能与当前问题无关，请以对话历史为准。"))
        return await handler(request.override(messages=[*history, current], system_message=system))
