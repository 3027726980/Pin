"""
Agent 业务逻辑（分类分表，统一入口）

类型：
  - simple_rag：SimpleRagAgentRepo（simple_rag_agents 表，知识库直接绑定）
  - general：GeneralAgentRepo（general_agents 表，工具注册）
  - workflow：预留，MVP 不做

校验：LLM 配置归属且 model_type=2；simple_rag 的知识库 / general 工具中的知识库归属当前用户
默认 system_prompt：不传时使用 RAG 模板（{agent_name} 占位替换）
默认检索参数：top_k / score_threshold 不传时取 config.yaml tools 节点
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.utils import to_uuid
from backend.models import GeneralAgents, KnowledgeBases, SimpleRagAgents, UserModelConfig, Users
from backend.repositories import (
    GeneralAgentRepo,
    KnowledgeBaseRepo,
    SimpleRagAgentRepo,
    UserModelConfigRepo,
)
from backend.schemas.agent import (
    AgentCreate,
    AgentListItem,
    AgentResponse,
    AgentUpdate,
    GeneralAgentCreate,
    SimpleRagAgentCreate,
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
        创建 Agent（按 type 分发到不同表）

        校验：LLM 配置归属且 model_type=2；知识库归属（simple_rag 的 kb_id / general 工具的 kb_id）
        """
        await AgentService._ensure_llm_config(db, user, data.llm_config_id)

        if data.type == "simple_rag":
            return await AgentService._create_simple_rag(db, user, data)
        return await AgentService._create_general(db, user, data)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user: Users,
        page: int = settings.pagination.default_page,
        page_size: int = settings.pagination.default_page_size,
        type_filter: str | None = None,
    ) -> PaginatedResponse:
        """
        当前用户的 Agent 列表（分页，可按 type 筛选）

        两种类型各查各表，合并后按创建时间倒序分页
        """
        if type_filter not in (None, "simple_rag", "general"):
            raise HTTPException(status_code=400, detail=f"不支持的 Agent 类型: {type_filter}")

        simple_items = []
        general_items = []
        if type_filter in (None, "simple_rag"):
            simple_items, _ = await SimpleRagAgentRepo.list_by_user(db, user.id, 1, 100000)
        if type_filter in (None, "general"):
            general_items, _ = await GeneralAgentRepo.list_by_user(db, user.id, 1, 100000)

        # 合并 + 按创建时间倒序
        all_items: list = sorted(
            [("simple_rag", a) for a in simple_items] + [("general", a) for a in general_items],
            key=lambda x: x[1].created_at,
            reverse=True,
        )
        total = len(all_items)
        paged = all_items[(page - 1) * page_size : page * page_size]

        kb_ids = {
            to_uuid(t["kb_id"])
            for _, a in paged
            for t in (a.tools if hasattr(a, "tools") else [{"kb_id": a.kb_id, "type": "rag"}])
            if t.get("type") == "rag" and t.get("kb_id")
        }
        kb_names = await AgentService._kb_name_map(db, user.id, list(kb_ids))
        llm_models = await AgentService._llm_model_map(db, user.id, [a.llm_config_id for _, a in paged])

        result_items = []
        for atype, a in paged:
            item = AgentListItem(
                id=a.id,
                type=atype,
                name=a.name,
                description=a.description,
                llm_model=llm_models.get(a.llm_config_id),
                status=a.status,
                created_at=a.created_at,
            )
            if atype == "simple_rag":
                item.kb_id = a.kb_id
                item.kb_name = kb_names.get(a.kb_id)
            else:
                item.tools = AgentService._tools_with_kb_name(a.tools, kb_names)
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
        获取单个 Agent 详情（自动定位类型）

        校验：存在性 → 归属 → 未删除
        """
        atype, agent = await AgentService._find_agent(db, user, agent_id)
        return await AgentService._to_response(db, user, atype, agent)

    @staticmethod
    async def update(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        data: AgentUpdate,
    ) -> AgentResponse:
        """
        编辑 Agent（type 不可改，按库中类型更新对应表字段）

        simple_rag：kb_id/top_k/score_threshold 等
        general：tools（整体替换）
        """
        atype, agent = await AgentService._find_agent(db, user, agent_id)

        if data.llm_config_id is not None and data.llm_config_id != agent.llm_config_id:
            await AgentService._ensure_llm_config(db, user, data.llm_config_id)

        if atype == "simple_rag":
            if data.kb_id is not None and data.kb_id != agent.kb_id:
                await AgentService._ensure_kb(db, user, data.kb_id)
            agent = await SimpleRagAgentRepo.update(
                db, agent,
                name=data.name,
                description=data.description,
                llm_config_id=data.llm_config_id,
                kb_id=data.kb_id,
                top_k=data.top_k,
                score_threshold=data.score_threshold,
                system_prompt=data.system_prompt,
                temperature=data.temperature,
                top_p=data.top_p,
                welcome_message=data.welcome_message,
                status=data.status,
            )
        else:
            if data.tools is not None:
                await AgentService._ensure_tools(db, user, data.tools)
            agent = await GeneralAgentRepo.update(
                db, agent,
                name=data.name,
                description=data.description,
                llm_config_id=data.llm_config_id,
                tools=([t.model_dump(mode="json", exclude={"kb_name"}) for t in data.tools]
                       if data.tools is not None else None),
                system_prompt=data.system_prompt,
                temperature=data.temperature,
                top_p=data.top_p,
                welcome_message=data.welcome_message,
                status=data.status,
            )

        await db.commit()
        await db.refresh(agent)
        return await AgentService._to_response(db, user, atype, agent)

    @staticmethod
    async def delete(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> None:
        """软删除 Agent（status → 9）"""
        atype, agent = await AgentService._find_agent(db, user, agent_id)
        if atype == "simple_rag":
            await SimpleRagAgentRepo.soft_delete(db, agent)
        else:
            await GeneralAgentRepo.soft_delete(db, agent)
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

        ids 可能混合两种类型：分别按归属更新对应表，合并统计
        """
        if action not in ("enable", "disable", "delete"):
            raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")
        status = 9 if action == "delete" else (1 if action == "enable" else 0)

        # 按类型分组更新（各表只更新属于该用户且未删除的记录）
        affected_simple = await SimpleRagAgentRepo.batch_update_status(db, user.id, ids, status)
        affected_general = await GeneralAgentRepo.batch_update_status(db, user.id, ids, status)
        affected = affected_simple + affected_general

        await db.commit()
        return BatchResult(
            success_count=affected,
            fail_count=len(ids) - affected,
        )

    # ═══════════════════════════════════════════════
    # 创建分发
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _create_simple_rag(
        db: AsyncSession,
        user: Users,
        data: SimpleRagAgentCreate,
    ) -> AgentResponse:
        """创建简单 RAG Agent：校验知识库，直接绑定字段"""
        await AgentService._ensure_kb(db, user, data.kb_id)

        prompt = data.system_prompt or DEFAULT_SYSTEM_PROMPT.replace("{agent_name}", data.name)
        agent = await SimpleRagAgentRepo.create(
            db,
            user_id=user.id,
            name=data.name,
            description=data.description,
            kb_id=data.kb_id,
            llm_config_id=data.llm_config_id,
            top_k=data.top_k or settings.tools.default_top_k,
            score_threshold=data.score_threshold if data.score_threshold is not None else settings.tools.default_score_threshold,
            system_prompt=prompt,
            temperature=data.temperature,
            top_p=data.top_p,
            welcome_message=data.welcome_message,
        )
        await db.commit()
        return await AgentService._to_response(db, user, "simple_rag", agent)

    @staticmethod
    async def _create_general(
        db: AsyncSession,
        user: Users,
        data: GeneralAgentCreate,
    ) -> AgentResponse:
        """创建综合 Agent：校验工具列表，工具配置入库"""
        await AgentService._ensure_tools(db, user, data.tools)

        prompt = data.system_prompt or DEFAULT_SYSTEM_PROMPT.replace("{agent_name}", data.name)
        agent = await GeneralAgentRepo.create(
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
        return await AgentService._to_response(db, user, "general", agent)

    # ═══════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _find_agent(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> tuple[str, object]:
        """
        按 id 定位 Agent（先查 general 再查 simple_rag）并校验归属 + 未删除

        返回 (type, orm对象)
        Raises: HTTPException 404
        """
        general = await GeneralAgentRepo.get_by_id(db, agent_id)
        if general is not None and general.status != 9 and general.user_id == user.id:
            return "general", general

        simple = await SimpleRagAgentRepo.get_by_id(db, agent_id)
        if simple is not None and simple.status != 9 and simple.user_id == user.id:
            return "simple_rag", simple

        raise HTTPException(status_code=404, detail="Agent 不存在")

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
    async def _to_response(
        db: AsyncSession,
        user: Users,
        atype: str,
        agent: object,
    ) -> AgentResponse:
        """ORM → Response，按类型补全 llm 摘要 / kb 名称 / 工具 kb 名称"""
        resp = AgentResponse(
            id=agent.id,
            type=atype,
            name=agent.name,
            description=agent.description,
            llm_config_id=agent.llm_config_id,
            system_prompt=agent.system_prompt,
            temperature=agent.temperature,
            top_p=agent.top_p,
            welcome_message=agent.welcome_message,
            status=agent.status,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

        llm_cfg = await UserModelConfigRepo.get_by_id(db, agent.llm_config_id)
        resp.llm_provider = llm_cfg.provider if llm_cfg else None
        resp.llm_model = llm_cfg.model_name if llm_cfg else None

        if atype == "simple_rag":
            kb = await KnowledgeBaseRepo.get_by_id(db, agent.kb_id)
            resp.kb_id = agent.kb_id
            resp.kb_name = kb.name if kb else None
            resp.top_k = agent.top_k
            resp.score_threshold = agent.score_threshold
        else:
            kb_ids = {to_uuid(t["kb_id"]) for t in agent.tools if t.get("type") == "rag" and t.get("kb_id")}
            kb_names = await AgentService._kb_name_map(db, user.id, list(kb_ids))
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
