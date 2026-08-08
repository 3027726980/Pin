"""
工具包 — Agent 能力单元

结构：
  tools/__init__.py    ← ToolRegistry 注册表（统一调度：校验/构建/补全）
  tools/common/        ← 通用工具类（BaseTool 抽象基类等）
  tools/agent/         ← Agent 可注册的工具（rag 等）

新增工具流程（调用方零改动）：
  1. tools/agent/ 下新建工具类（继承 BaseTool：type/description/name_ref_keys + validate_config/build_langchain/execute）
  2. 在 ToolRegistry.TOOLS 注册 type → 工具类
  3. schemas 中 ToolConfig.type 扩充对应 Literal 成员
"""
from backend.tools.common.base import BaseTool
from backend.tools.agent.rag import RAGTool
from backend.core.utils import to_uuid
from backend.schemas.agent import ToolConfig
from fastapi import HTTPException


class ToolRegistry:
    """工具注册表：按 type 统一调度工具的校验、LangChain 构建、响应补全"""

    TOOLS: dict[str, type] = {
        "rag": RAGTool,
    }

    # ═══════════════════════════════════════════════
    # 内部
    # ═══════════════════════════════════════════════

    @staticmethod
    def _get(tool_type: str) -> type:
        """按 type 取工具类，未知类型抛 400"""
        cls = ToolRegistry.TOOLS.get(tool_type)
        if cls is None:
            raise HTTPException(status_code=400, detail=f"不支持的工具类型: {tool_type}")
        return cls

    # ═══════════════════════════════════════════════
    # 配置校验（创建/编辑 Agent 时调用）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def validate_all(db, user, tools: list[dict]) -> None:
        """
        校验工具列表中的全部工具配置

        每个工具调用自己的 validate_config（如 rag 校验知识库归属/状态）
        """
        for tool in tools:
            cls = ToolRegistry._get(tool.get("type"))
            await cls.validate_config(db, user, tool)

    # ═══════════════════════════════════════════════
    # LangChain 工具构建（general Agent 对话时调用）
    # ═══════════════════════════════════════════════

    @staticmethod
    def build_langchain_tools(
        db,
        user,
        tools: list[dict],
        **kwargs,
    ) -> list:
        """
        将工具配置列表构建为 LangChain 工具列表（供 create_agent 注册）

        每个工具调用自己的 build_langchain（闭包绑定 db/user/config）
        **kwargs 透传给各工具（如 citations_store），由工具自行决定是否使用
        """
        result = []
        for tool in tools:
            cls = ToolRegistry._get(tool.get("type"))
            result.append(cls.build_langchain(db, user, tool, **kwargs))
        return result

    # ═══════════════════════════════════════════════
    # 响应补全（列表/详情时调用）
    # ═══════════════════════════════════════════════

    @staticmethod
    def collect_refs(tools: list[dict]) -> dict[str, list]:
        """
        收集工具声明需要补全名称的引用 id

        按配置字段聚合：{"kb_id": [uuid, ...]}（rag 工具声明 name_ref_keys = {"kb_id": "kb_name"}）
        """
        refs: dict[str, list] = {}
        for tool in tools:
            cls = ToolRegistry._get(tool.get("type"))
            for cfg_key in cls.name_ref_keys:
                val = tool.get(cfg_key)
                if val:
                    refs.setdefault(cfg_key, []).append(to_uuid(val))
        return refs

    @staticmethod
    def enrich_tools(tools: list[dict], ref_names: dict[str, dict]) -> list[ToolConfig]:
        """
        工具配置 → ToolConfig 响应，按各工具声明的 name_ref_keys 补全名称

        参数:
            tools: 工具配置列表（来自 general_agents.tools）
            ref_names: 名称映射，如 {"kb_id": {uuid: name}}（由 collect_refs + 批量查询得到）
        """
        result = []
        for tool in tools:
            cfg = ToolConfig.model_validate(tool)
            cls = ToolRegistry._get(tool.get("type"))
            for cfg_key, resp_key in cls.name_ref_keys.items():
                val = tool.get(cfg_key)
                name_map = ref_names.get(cfg_key, {})
                setattr(cfg, resp_key, name_map.get(to_uuid(val)) if val else None)
            result.append(cfg)
        return result


__all__ = ["BaseTool", "RAGTool", "ToolRegistry"]
