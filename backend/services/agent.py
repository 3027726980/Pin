"""
Agent 业务逻辑

- Agent CRUD：创建 → 列表 → 详情 → 编辑 → 软删除 → 批量
- 校验：LLM 配置归属当前用户且 model_type=2；工具配置中的知识库归属当前用户
- 默认 system_prompt：不传时使用 RAG 模板（{agent_name} 占位替换）
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models import Agents, KnowledgeBases, UserModelConfig, Users
from backend.repositories import AgentRepo, KnowledgeBaseRepo, UserModelConfigRepo
from backend.schemas.agent import (
    AgentCreate,
    AgentListItem,
    AgentResponse,
    AgentUpdate,
    ToolConfig,
)
from backend.schemas.knowledge import BatchResult, PaginatedResponse

# 默认 RAG 模板（{agent_name} 在创建时替换为实际名称）
DEFAULT_SYSTEM_PROMPT = (
    "你是「{agent_name}」，一个基于知识库回答问题的 AI 助手。\n"
    "请仅依据提供的资料片段回答用户问题，引用资料时标注来源编号（如 [1]）。\n"
    "如果资料不足以回答，请如实说明\"知识库中没有相关信息\"，不要编造。\n"
    "回答使用中文，简洁准确。"
)


class AgentService:
    """Agent 业务逻辑 —— 不依赖 HTTP 请求/响应，只处理数据和规则"""

    # ═══════════════════════════════════════════════
    # CRUD
    # ═══════════════════════════════════════════════

    @staticmethod
    async def create(
        db: AsyncSession,
        user: Users,
        data: AgentCreate,
    ) -> AgentResponse:
        """
        创建 Agent

        校验：LLM 配置归属且为 LLM 类型（model_type=2）；工具配置中的知识库归属
        system_prompt 不传 → 使用默认 RAG 模板
        """
        await AgentService._ensure_llm_config(db, user, data.llm_config_id)
        await AgentService._ensure_tools(db, user, data.tools)

        prompt = data.system_prompt or DEFAULT_SYSTEM_PROMPT.replace("{agent_name}", data.name)
        agent = await AgentRepo.create(
            db,
            user_id=user.id,
            name=data.name,
            description=data.description,
            llm_config_id=data.llm_config_id,
            tools=[t.model_dump(mode="json", exclude={"kb_name"}) for t in data.tools],
            system_prompt=prompt,
            temperature=data.temperature,
            top_p=data.top_p,
            welcome_message=data.welcome_message,
        )
        await db.commit()
        return await AgentService._to_response(db, agent)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user: Users,
        page: int = settings.pagination.default_page,
        page_size: int = settings.pagination.default_page_size,
    ) -> PaginatedResponse:
        """
        当前用户的 Agent 列表（分页）

        自动过滤 status=9，按创建时间倒序
        """
        items, total = await AgentRepo.list_by_user(db, user.id, page, page_size)
        kb_ids = {UUID(tool["kb_id"]) for a in items for tool in a.tools if tool.get("type") == "rag"}
        kb_names = await AgentService._kb_name_map(db, user.id, list(kb_ids))
        llm_models = await AgentService._llm_model_map(db, user.id, [a.llm_config_id for a in items])

        result_items = []
        for a in items:
            item = AgentListItem.model_validate(a)
            item.tools = AgentService._tools_with_kb_name(a.tools, kb_names)
            item.llm_model = llm_models.get(a.llm_config_id)
            result_items.append(item)

        return PaginatedResponse(
            items=result_items,
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    async def get(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> AgentResponse:
        """
        获取单个 Agent 详情

        校验：存在性 → 归属 → 未删除
        """
        agent = await AgentService._get_agent_for_user(db, user, agent_id)
        return await AgentService._to_response(db, agent)

    @staticmethod
    async def update(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        data: AgentUpdate,
    ) -> AgentResponse:
        """
        编辑 Agent

        仅更新传入的非 None 字段；llm_config_id / tools 变更时重新校验
        """
        agent = await AgentService._get_agent_for_user(db, user, agent_id)

        if data.llm_config_id is not None and data.llm_config_id != agent.llm_config_id:
            await AgentService._ensure_llm_config(db, user, data.llm_config_id)
        if data.tools is not None:
            await AgentService._ensure_tools(db, user, data.tools)

        agent = await AgentRepo.update(
            db, agent,
            name=data.name,
            description=data.description,
            llm_config_id=data.llm_config_id,
            tools=([t.model_dump(mode="json", exclude={"kb_name"}) for t in data.tools] if data.tools is not None else None),
            system_prompt=data.system_prompt,
            temperature=data.temperature,
            top_p=data.top_p,
            welcome_message=data.welcome_message,
            status=data.status,
        )
        await db.commit()
        await db.refresh(agent)  # 重新加载 onupdate 触发的 updated_at
        return await AgentService._to_response(db, agent)

    @staticmethod
    async def delete(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> None:
        """
        软删除 Agent（status → 9）
        """
        agent = await AgentService._get_agent_for_user(db, user, agent_id)
        await AgentRepo.soft_delete(db, agent)
        await db.commit()

    # ═══════════════════════════════════════════════
    # 批量操作
    # ═══════════════════════════════════════════════

    @staticmethod
    async def batch(
        db: AsyncSession,
        user: Users,
        ids: list[UUID],
        action: str,
    ) -> BatchResult:
        """
        批量操作 Agent：enable / disable / delete

        仅操作属于当前用户且未删除的 Agent
        """
        if action == "delete":
            affected = await AgentRepo.batch_update_status(db, user.id, ids, 9)
        elif action == "enable":
            affected = await AgentRepo.batch_update_status(db, user.id, ids, 1)
        elif action == "disable":
            affected = await AgentRepo.batch_update_status(db, user.id, ids, 0)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")

        await db.commit()
        return BatchResult(
            success_count=affected,
            fail_count=len(ids) - affected,
        )

    # ═══════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _get_agent_for_user(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> Agents:
        """
        查 Agent + 校验归属 + 校验未删除

        Raises: HTTPException 404（不存在/已删除/不属于当前用户，统一报不存在）
        """
        agent = await AgentRepo.get_by_id(db, agent_id)
        if agent is None or agent.status == 9 or agent.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        return agent

    @staticmethod
    async def _ensure_llm_config(db: AsyncSession, user: Users, cfg_id: UUID) -> None:
        """校验 LLM 配置：存在 + 归属 + model_type=2"""
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id or cfg.model_type != 2:
            raise HTTPException(status_code=400, detail="LLM 模型配置无效")

    @staticmethod
    async def _ensure_tools(db: AsyncSession, user: Users, tools: list[ToolConfig]) -> None:
        """校验工具配置：rag 工具的知识库归属 + 未删除 + 启用"""
        for tool in tools:
            if tool.type == "rag":
                await AgentService._ensure_kb(db, user, tool.kb_id)

    @staticmethod
    async def _ensure_kb(db: AsyncSession, user: Users, kb_id: UUID) -> None:
        """校验知识库归属 + 未删除 + 启用"""
        kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
        if kb is None or kb.status == 9 or kb.user_id != user.id:
            raise HTTPException(status_code=404, detail="知识库不存在")
        if kb.status == 0:
            raise HTTPException(status_code=400, detail="知识库已禁用")

    @staticmethod
    async def _to_response(db: AsyncSession, agent: Agents) -> AgentResponse:
        """ORM → Response，补全 llm 配置摘要 + 工具 kb 名称"""
        resp = AgentResponse.model_validate(agent)

        llm_cfg = await UserModelConfigRepo.get_by_id(db, agent.llm_config_id)
        resp.llm_provider = llm_cfg.provider if llm_cfg else None
        resp.llm_model = llm_cfg.model_name if llm_cfg else None

        kb_ids = {UUID(t["kb_id"]) for t in agent.tools if t.get("type") == "rag"}
        kb_names = await AgentService._kb_name_map(db, user_id=agent.user_id, kb_ids=list(kb_ids))
        resp.tools = AgentService._tools_with_kb_name(agent.tools, kb_names)
        return resp

    @staticmethod
    def _tools_with_kb_name(tools: list[dict], kb_names: dict[UUID, str]) -> list[ToolConfig]:
        """工具 dict → ToolConfig，补全 rag 工具的 kb_name"""
        result = []
        for t in tools:
            cfg = ToolConfig.model_validate(t)
            if cfg.type == "rag":
                cfg.kb_name = kb_names.get(cfg.kb_id)
            result.append(cfg)
        return result

    @staticmethod
    async def _kb_name_map(
        db: AsyncSession, user_id: UUID, kb_ids: list[UUID]
    ) -> dict[UUID, str]:
        """批量查知识库名称 → {kb_id: name}"""
        if not kb_ids:
            return {}
        q = select(KnowledgeBases.id, KnowledgeBases.name).where(
            KnowledgeBases.id.in_(kb_ids),
            KnowledgeBases.user_id == user_id,
        )
        rows = (await db.execute(q)).all()
        return {r.id: r.name for r in rows}

    @staticmethod
    async def _llm_model_map(
        db: AsyncSession, user_id: UUID, cfg_ids: list[UUID]
    ) -> dict[UUID, str]:
        """批量查 LLM 配置模型名 → {cfg_id: model_name}"""
        if not cfg_ids:
            return {}
        q = select(UserModelConfig.id, UserModelConfig.model_name).where(
            UserModelConfig.id.in_(cfg_ids),
            UserModelConfig.user_id == user_id,
        )
        rows = (await db.execute(q)).all()
        return {r.id: r.model_name for r in rows}
