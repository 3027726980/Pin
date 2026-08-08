"""
工具包 — Agent 能力单元

结构：
  tools/__init__.py    ← ToolRegistry 注册表（按 type 分发）
  tools/common/        ← 通用工具类（BaseTool 抽象基类等）
  tools/agent/         ← Agent 可注册的工具（rag 等）

新增工具流程：
  1. tools/agent/ 下新建工具类（继承 BaseTool，实现 execute）
  2. 在 ToolRegistry.TOOLS 注册 type → 工具类
  3. schemas 中 ToolConfig.type 扩充对应 Literal 成员
"""
from backend.tools.common.base import BaseTool
from backend.tools.agent.rag import RAGTool


class ToolRegistry:
    """工具注册表：按 type 分发执行"""

    TOOLS: dict[str, type] = {
        "rag": RAGTool,
    }

    @staticmethod
    async def execute_all(
        db,
        user,
        tools: list[dict],
        message: str,
    ) -> dict[str, list]:
        """
        执行工具列表中的全部工具

        参数:
            tools: 工具配置列表（来自 general_agents.tools JSONB）
            message: 用户消息

        返回: {tool_type: 工具输出}，如 {"rag": [Citation, ...]}
        """
        from fastapi import HTTPException

        results: dict[str, list] = {}
        for tool in tools:
            tool_cls = ToolRegistry.TOOLS.get(tool.get("type"))
            if tool_cls is None:
                raise HTTPException(status_code=400, detail=f"不支持的工具类型: {tool.get('type')}")
            results[tool_cls.type] = await tool_cls.execute(db, user, tool, message)
        return results


__all__ = ["BaseTool", "RAGTool", "ToolRegistry"]
