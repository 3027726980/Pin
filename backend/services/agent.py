"""
Agent 业务逻辑（分类分表 + 索引表，统一入口）

数据模型：
  - agent_index：索引表（所有 Agent 基础信息，id 与类型表共用）—— 列表/定位走此表
  - simple_rag_agents：简单 RAG Agent 类型表（知识库直接绑定）
  - general_agents：综合 Agent 类型表（工具注册）
  - workflow：预留，MVP 不做

一致性：创建/编辑/删除时事务内双写（索引表 + 类型表），id 共用。
校验：LLM 配置归属且 model_type=2；simple_rag 的知识库 / general 工具中的知识库归属当前用户
默认 system_prompt：不传时使用 RAG 模板（{agent_name} 占位替换）
默认检索参数：top_k / score_threshold 不传时取 config.yaml tools 节点
"""
import re
from uuid import UUID, uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.constants import DEFAULT_INTENT_RULES, DEFAULT_SYSTEM_PROMPT
from backend.models import GeneralAgents, KnowledgeBases, SimpleRagAgents, UserModelConfig, Users
from backend.repositories import (
    AgentIndexRepo,
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
    IntentRules,
    SimpleRagAgentCreate,
    ToolConfig,
)
from backend.schemas.knowledge import BatchResult, PaginatedResponse


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
        创建 Agent（按 type 分发到不同类型表，事务内双写索引表）

        校验：LLM 配置归属且 model_type=2；知识库归属（simple_rag 的 kb_id / general 工具的 kb_id）；
        总结模型配置（summary_llm_config_id 非空时同 LLM 校验）
        """
        await AgentService._ensure_llm_config(db, user, data.llm_config_id)
        if data.summary_llm_config_id is not None:
            await AgentService._ensure_llm_config(
                db, user, data.summary_llm_config_id)
        if getattr(data, "enhance_llm_config_id", None) is not None:
            await AgentService._ensure_llm_config(
                db, user, data.enhance_llm_config_id)
        if getattr(data, "rerank_config_id", None) is not None:
            await AgentService._ensure_rerank_config(
                db, user, data.rerank_config_id)
        # 开启 Rerank 必须显式选择模型
        if getattr(data, "rerank_enabled", None) is True \
                and getattr(data, "rerank_config_id", None) is None:
            raise HTTPException(
                status_code=400, detail="开启 Rerank 必须选择 Rerank 模型（可在模型配置页创建 Rerank 类型配置）")

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
        当前用户的 Agent 列表（索引表单表 SQL 分页，可按 type 筛选）

        展示字段（llm_model / kb_name / tools）按类型批量查类型表补全
        """
        if type_filter not in (None, "simple_rag", "general"):
            raise HTTPException(status_code=400, detail=f"不支持的 Agent 类型: {type_filter}")

        items, total = await AgentIndexRepo.list_by_user(db, user.id, page, page_size, type_filter)

        # 按类型批量查类型表（补 llm_config_id / kb_id / tools 等详情）
        detail_map: dict[UUID, object] = {}
        type_ids: dict[str, list[UUID]] = {}
        for it in items:
            type_ids.setdefault(it.type, []).append(it.id)
        for t, ids in type_ids.items():
            model = SimpleRagAgents if t == "simple_rag" else GeneralAgents
            rows = (await db.execute(select(model).where(model.id.in_(ids)))).scalars().all()
            for r in rows:
                detail_map[r.id] = r

        # 展示字段收集
        llm_models = await AgentService._llm_model_map(
            db, user.id, [detail_map[i.id].llm_config_id for i in items if i.id in detail_map]
        )
        from backend.tools import ToolRegistry

        simple_kb_ids = [
            detail_map[i.id].kb_id for i in items
            if i.type == "simple_rag" and i.id in detail_map
        ]
        simple_kb_names = await AgentService._kb_name_map(db, user.id, simple_kb_ids)
        general_tools = [
            t for i in items if i.id in detail_map and hasattr(detail_map[i.id], "tools")
            for t in detail_map[i.id].tools
        ]
        refs = ToolRegistry.collect_refs(general_tools)
        ref_names: dict = {}
        if refs.get("kb_id"):
            ref_names["kb_id"] = await AgentService._kb_name_map(db, user.id, refs["kb_id"])

        result_items = []
        for it in items:
            detail = detail_map.get(it.id)
            item = AgentListItem(
                id=it.id,
                type=it.type,
                name=it.name,
                description=it.description,
                llm_model=llm_models.get(detail.llm_config_id) if detail else None,
                status=it.status,
                created_at=it.created_at,
            )
            if it.type == "simple_rag" and detail:
                item.kb_id = detail.kb_id
                item.kb_name = simple_kb_names.get(detail.kb_id)
            elif it.type == "general" and detail:
                item.tools = ToolRegistry.enrich_tools(detail.tools, ref_names)
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
        获取单个 Agent 详情（索引表定位类型 → 类型表查详情）

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
        编辑 Agent（type 不可改，索引表定位类型，双表更新）

        simple_rag：kb_id/top_k/score_threshold 等
        general：tools（整体替换）
        """
        atype, agent = await AgentService._find_agent(db, user, agent_id)

        if data.llm_config_id is not None and data.llm_config_id != agent.llm_config_id:
            await AgentService._ensure_llm_config(db, user, data.llm_config_id)
        if (data.summary_llm_config_id is not None
                and data.summary_llm_config_id != agent.summary_llm_config_id):
            await AgentService._ensure_llm_config(
                db, user, data.summary_llm_config_id)
        if (data.enhance_llm_config_id is not None
                and data.enhance_llm_config_id != getattr(agent, "enhance_llm_config_id", None)):
            await AgentService._ensure_llm_config(
                db, user, data.enhance_llm_config_id)
        if (data.rerank_config_id is not None
                and data.rerank_config_id != getattr(agent, "rerank_config_id", None)):
            await AgentService._ensure_rerank_config(
                db, user, data.rerank_config_id)
        # 开启 Rerank 必须显式选择模型（按最终值校验，兼容部分更新）
        final_rerank = (data.rerank_enabled if data.rerank_enabled is not None
                        else getattr(agent, "rerank_enabled", False))
        final_cfg = (data.rerank_config_id if data.rerank_config_id is not None
                     else getattr(agent, "rerank_config_id", None))
        if final_rerank and final_cfg is None:
            raise HTTPException(
                status_code=400, detail="开启 Rerank 必须选择 Rerank 模型（可在模型配置页创建 Rerank 类型配置）")

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
                summary_llm_config_id=data.summary_llm_config_id,
                mqe_enabled=data.mqe_enabled,
                hyde_enabled=data.hyde_enabled,
                mqe_query_count=data.mqe_query_count,
                rerank_enabled=data.rerank_enabled,
                enhance_llm_config_id=data.enhance_llm_config_id,
                rerank_config_id=data.rerank_config_id,
                max_tokens=data.max_tokens,
            )
        else:
            if data.tools is not None:
                await AgentService._ensure_tools(db, user, data.tools)
            AgentService._validate_intent_rules(data.intent_rules)
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
                summary_llm_config_id=data.summary_llm_config_id,
                enhance_llm_config_id=data.enhance_llm_config_id,
                rerank_config_id=data.rerank_config_id,
                max_tokens=data.max_tokens,
                intent_rules=(data.intent_rules.model_dump(mode="json")
                              if data.intent_rules is not None else None),
                intent_routing=data.intent_routing,
                plan_enabled=data.plan_enabled,
                reflect_enabled=data.reflect_enabled,
            )

        # 索引表基础字段同步
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is not None:
            await AgentIndexRepo.update(
                db, entry,
                name=data.name,
                description=data.description,
                status=data.status,
                rate_limit_per_min=data.rate_limit_per_min,
                allowed_domains=data.allowed_domains,
                anonymous_retention_days=data.anonymous_retention_days,
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
        """软删除 Agent（双表：类型表 + 索引表，status → 9）"""
        atype, agent = await AgentService._find_agent(db, user, agent_id)
        if atype == "simple_rag":
            await SimpleRagAgentRepo.soft_delete(db, agent)
        else:
            await GeneralAgentRepo.soft_delete(db, agent)
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is not None:
            await AgentIndexRepo.soft_delete(db, entry)
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

        索引表 + 两张类型表同步更新（ids 可能混合类型）
        """
        if action not in ("enable", "disable", "delete"):
            raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")
        status = 9 if action == "delete" else (1 if action == "enable" else 0)

        affected_index = await AgentIndexRepo.batch_update_status(db, user.id, ids, status)
        affected_simple = await SimpleRagAgentRepo.batch_update_status(db, user.id, ids, status)
        affected_general = await GeneralAgentRepo.batch_update_status(db, user.id, ids, status)

        await db.commit()
        return BatchResult(
            success_count=affected_index,
            fail_count=len(ids) - affected_index,
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
        """创建简单 RAG Agent：校验知识库，类型表 + 索引表双写（同 id）"""
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
            summary_llm_config_id=data.summary_llm_config_id,
            mqe_enabled=data.mqe_enabled if data.mqe_enabled is not None else settings.tools.default_mqe_enabled,
            hyde_enabled=data.hyde_enabled if data.hyde_enabled is not None else settings.tools.default_hyde_enabled,
            mqe_query_count=data.mqe_query_count or settings.tools.default_mqe_query_count,
            rerank_enabled=data.rerank_enabled if data.rerank_enabled is not None else settings.tools.default_rerank_enabled,
            enhance_llm_config_id=data.enhance_llm_config_id,
            rerank_config_id=data.rerank_config_id,
            max_tokens=data.max_tokens,
        )
        # 索引表（id 共用）
        await AgentIndexRepo.create(
            db, agent.id, user.id, "simple_rag", agent.name, agent.description
        )
        await db.commit()
        return await AgentService._to_response(db, user, "simple_rag", agent)

    @staticmethod
    async def _create_general(
        db: AsyncSession,
        user: Users,
        data: GeneralAgentCreate,
    ) -> AgentResponse:
        """创建综合 Agent：校验工具列表，类型表 + 索引表双写（同 id）"""
        await AgentService._ensure_tools(db, user, data.tools)
        AgentService._validate_intent_rules(data.intent_rules)

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
            summary_llm_config_id=data.summary_llm_config_id,
            enhance_llm_config_id=data.enhance_llm_config_id,
            rerank_config_id=data.rerank_config_id,
            max_tokens=data.max_tokens,
            intent_rules=(data.intent_rules.model_dump(mode="json")
                          if data.intent_rules is not None
                          else DEFAULT_INTENT_RULES),
            intent_routing=data.intent_routing,
            plan_enabled=data.plan_enabled,
            reflect_enabled=data.reflect_enabled,
        )
        # 索引表（id 共用）
        await AgentIndexRepo.create(
            db, agent.id, user.id, "general", agent.name, agent.description
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
        索引表定位 Agent（type）→ 类型表查详情，校验归属 + 未删除

        返回 (type, orm对象)
        Raises: HTTPException 404
        """
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is None or entry.status == 9 or entry.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")

        if entry.type == "simple_rag":
            agent = await SimpleRagAgentRepo.get_by_id(db, agent_id)
        else:
            agent = await GeneralAgentRepo.get_by_id(db, agent_id)

        if agent is None or agent.status == 9:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        return entry.type, agent

    @staticmethod
    async def _ensure_llm_config(db: AsyncSession, user: Users, cfg_id: UUID) -> None:
        """校验 LLM 配置：存在 + 归属 + model_type=2"""
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id or cfg.model_type != 2:
            raise HTTPException(status_code=400, detail="LLM 模型配置无效")

    @staticmethod
    async def _ensure_rerank_config(db: AsyncSession, user: Users, cfg_id: UUID) -> None:
        """校验 Rerank 配置：存在 + 归属 + model_type=3"""
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id or cfg.model_type != 3:
            raise HTTPException(status_code=400, detail="Rerank 模型配置无效")

    @staticmethod
    async def _ensure_tools(db: AsyncSession, user: Users, tools: list[ToolConfig]) -> None:
        """校验工具配置（各工具自带校验逻辑，如 rag 校验知识库归属）"""
        from backend.tools import ToolRegistry

        await ToolRegistry.validate_all(
            db, user, [t.model_dump(mode="json", exclude={"kb_name"}) for t in tools]
        )

    @staticmethod
    def _validate_intent_rules(rules: IntentRules | None) -> None:
        """校验意图规则结构：kind 对应字段必填；regex 可编译

        Raises: HTTPException 422
        """
        if rules is None:
            return
        for r in rules.rules:
            if r.kind == "keyword" and not r.keywords:
                raise HTTPException(status_code=422, detail=f"规则「{r.name}」缺少关键词")
            if r.kind == "regex":
                if not r.pattern:
                    raise HTTPException(status_code=422, detail=f"规则「{r.name}」缺少正则")
                try:
                    re.compile(r.pattern)
                except re.error:
                    raise HTTPException(status_code=422, detail=f"规则「{r.name}」正则表达式非法")
            if r.kind == "length" and r.max_length is None:
                raise HTTPException(status_code=422, detail=f"规则「{r.name}」缺少长度上限")

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
            summary_llm_config_id=agent.summary_llm_config_id,
            system_prompt=agent.system_prompt,
            temperature=agent.temperature,
            top_p=agent.top_p,
            max_tokens=agent.max_tokens,
            welcome_message=agent.welcome_message,
            status=agent.status,
            created_at=agent.created_at,
            updated_at=agent.updated_at,
        )

        llm_cfg = await UserModelConfigRepo.get_by_id(db, agent.llm_config_id)
        resp.llm_provider = llm_cfg.provider if llm_cfg else None
        resp.llm_model = llm_cfg.model_name if llm_cfg else None
        # Phase 4.6 检索增强模型引用（Agent 级，两类型都有）
        resp.enhance_llm_config_id = agent.enhance_llm_config_id
        resp.rerank_config_id = agent.rerank_config_id

        # 嵌入治理参数（agent_index 表）
        entry = await AgentIndexRepo.get_by_id(db, agent.id)
        if entry is not None:
            resp.rate_limit_per_min = entry.rate_limit_per_min
            resp.allowed_domains = entry.allowed_domains or []
            resp.anonymous_retention_days = entry.anonymous_retention_days

        if atype == "simple_rag":
            kb = await KnowledgeBaseRepo.get_by_id(db, agent.kb_id)
            resp.kb_id = agent.kb_id
            resp.kb_name = kb.name if kb else None
            resp.top_k = agent.top_k
            resp.score_threshold = agent.score_threshold
            resp.mqe_enabled = agent.mqe_enabled
            resp.hyde_enabled = agent.hyde_enabled
            resp.mqe_query_count = agent.mqe_query_count
            resp.rerank_enabled = agent.rerank_enabled
        else:
            from backend.tools import ToolRegistry

            refs = ToolRegistry.collect_refs(agent.tools)
            ref_names: dict = {}
            if refs.get("kb_id"):
                ref_names["kb_id"] = await AgentService._kb_name_map(db, user.id, refs["kb_id"])
            resp.tools = ToolRegistry.enrich_tools(agent.tools, ref_names)
            resp.intent_rules = IntentRules.model_validate(agent.intent_rules or {})
            resp.intent_routing = agent.intent_routing
            resp.plan_enabled = agent.plan_enabled
            resp.reflect_enabled = agent.reflect_enabled
        return resp

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
