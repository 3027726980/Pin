"""
Agent 数据访问（分类分表）

- SimpleRagAgentRepo：simple_rag_agents 表（简单 RAG Agent，仅 RAG 功能）
- GeneralAgentRepo：general_agents 表（综合 Agent，工具注册）

所有方法接收外部传入的 AsyncSession，不自行管理事务边界。
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentIndex, GeneralAgents, SimpleRagAgents


class AgentIndexRepo:
    """agent_index 表 CRUD —— 只写 SQL，不管业务规则"""

    @staticmethod
    async def create(
        db: AsyncSession,
        agent_id: UUID,
        user_id: UUID,
        type: str,
        name: str,
        description: str | None,
    ) -> AgentIndex:
        """
        创建索引记录（id 与类型表共用）

        只做 insert + flush，不 commit（由调用方控制事务）
        """
        entry = AgentIndex(
            id=agent_id,
            user_id=user_id,
            type=type,
            name=name,
            description=description,
        )
        db.add(entry)
        await db.flush()
        return entry

    @staticmethod
    async def get_by_id(db: AsyncSession, agent_id: UUID) -> AgentIndex | None:
        """按主键查询单条（不做状态过滤，调用方自行判断）"""
        return await db.get(AgentIndex, agent_id)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
        type_filter: str | None = None,
    ) -> tuple[list[AgentIndex], int]:
        """
        按用户分页查询（过滤 status=9，可按 type 筛选，按创建时间倒序）

        返回 (列表, 总数)
        """
        cond = [AgentIndex.user_id == user_id, AgentIndex.status != 9]
        if type_filter:
            cond.append(AgentIndex.type == type_filter)

        count_q = select(func.count()).where(*cond)
        total = (await db.execute(count_q)).scalar() or 0

        q = (
            select(AgentIndex)
            .where(*cond)
            .order_by(AgentIndex.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def update(
        db: AsyncSession,
        entry: AgentIndex,
        **kwargs,
    ) -> AgentIndex:
        """更新基础字段（仅更新传入的非 None 值），只 flush 不 commit"""
        for key, value in kwargs.items():
            if value is not None:
                setattr(entry, key, value)
        await db.flush()
        return entry

    @staticmethod
    async def soft_delete(db: AsyncSession, entry: AgentIndex) -> None:
        """软删除：status → 9，只 flush 不 commit"""
        entry.status = 9
        await db.flush()

    @staticmethod
    async def batch_update_status(
        db: AsyncSession,
        user_id: UUID,
        ids: list[UUID],
        status: int,
    ) -> int:
        """批量更新状态（仅属于该用户且未删除），返回实际更新行数"""
        from sqlalchemy import update as _update

        stmt = (
            _update(AgentIndex)
            .where(
                AgentIndex.id.in_(ids),
                AgentIndex.user_id == user_id,
                AgentIndex.status != 9,
            )
            .values(status=status)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount


class SimpleRagAgentRepo:
    """simple_rag_agents 表 CRUD —— 只写 SQL，不管业务规则"""

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        name: str,
        description: str | None,
        kb_id: UUID,
        llm_config_id: UUID,
        top_k: int,
        score_threshold: float,
        system_prompt: str,
        temperature: float = 0.7,
        top_p: float = 0.9,
        welcome_message: str | None = None,
    ) -> SimpleRagAgents:
        """
        创建简单 RAG Agent 记录

        只做 insert + flush，不 commit（由调用方控制事务）
        返回带 id 的 ORM 对象
        """
        agent = SimpleRagAgents(
            user_id=user_id,
            name=name,
            description=description,
            kb_id=kb_id,
            llm_config_id=llm_config_id,
            top_k=top_k,
            score_threshold=score_threshold,
            system_prompt=system_prompt,
            temperature=temperature,
            top_p=top_p,
            welcome_message=welcome_message,
        )
        db.add(agent)
        await db.flush()
        return agent

    @staticmethod
    async def get_by_id(db: AsyncSession, agent_id: UUID) -> SimpleRagAgents | None:
        """按主键查询单条（不做状态过滤，调用方自行判断）"""
        return await db.get(SimpleRagAgents, agent_id)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[SimpleRagAgents], int]:
        """
        按用户分页查询（过滤 status=9，按创建时间倒序）
        返回 (列表, 总数)
        """
        count_q = select(func.count()).where(
            SimpleRagAgents.user_id == user_id,
            SimpleRagAgents.status != 9,
        )
        total = (await db.execute(count_q)).scalar() or 0

        q = (
            select(SimpleRagAgents)
            .where(SimpleRagAgents.user_id == user_id, SimpleRagAgents.status != 9)
            .order_by(SimpleRagAgents.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def update(
        db: AsyncSession,
        agent: SimpleRagAgents,
        **kwargs,
    ) -> SimpleRagAgents:
        """更新字段（仅更新传入的非 None 值），只 flush 不 commit"""
        for key, value in kwargs.items():
            if value is not None:
                setattr(agent, key, value)
        await db.flush()
        return agent

    @staticmethod
    async def soft_delete(db: AsyncSession, agent: SimpleRagAgents) -> None:
        """软删除：status → 9，只 flush 不 commit"""
        agent.status = 9
        await db.flush()

    @staticmethod
    async def batch_update_status(
        db: AsyncSession,
        user_id: UUID,
        ids: list[UUID],
        status: int,
    ) -> int:
        """批量更新状态（仅属于该用户且未删除），返回实际更新行数"""
        from sqlalchemy import update as _update

        stmt = (
            _update(SimpleRagAgents)
            .where(
                SimpleRagAgents.id.in_(ids),
                SimpleRagAgents.user_id == user_id,
                SimpleRagAgents.status != 9,
            )
            .values(status=status)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    @staticmethod
    async def find_by_model_config(
        db: AsyncSession,
        config_id: UUID,
    ) -> list[SimpleRagAgents]:
        """
        查找使用指定 LLM 配置的简单 RAG Agent（仅未删除）

        软删除记录不拦截配置删除（FK 为 ON DELETE SET NULL，自动置空）
        """
        q = select(SimpleRagAgents).where(
            SimpleRagAgents.llm_config_id == config_id,
            SimpleRagAgents.status != 9,
        )
        result = await db.execute(q)
        return list(result.scalars().all())


class GeneralAgentRepo:
    """general_agents 表 CRUD —— 只写 SQL，不管业务规则"""

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        name: str,
        description: str | None,
        llm_config_id: UUID,
        tools: list[dict],
        system_prompt: str,
        temperature: float = 0.7,
        top_p: float = 0.9,
        welcome_message: str | None = None,
    ) -> GeneralAgents:
        """
        创建综合 Agent 记录

        只做 insert + flush，不 commit（由调用方控制事务）
        返回带 id 的 ORM 对象
        """
        agent = GeneralAgents(
            user_id=user_id,
            name=name,
            description=description,
            llm_config_id=llm_config_id,
            tools=tools,
            system_prompt=system_prompt,
            temperature=temperature,
            top_p=top_p,
            welcome_message=welcome_message,
        )
        db.add(agent)
        await db.flush()
        return agent

    @staticmethod
    async def get_by_id(db: AsyncSession, agent_id: UUID) -> GeneralAgents | None:
        """按主键查询单条（不做状态过滤，调用方自行判断）"""
        return await db.get(GeneralAgents, agent_id)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[GeneralAgents], int]:
        """
        按用户分页查询（过滤 status=9，按创建时间倒序）
        返回 (列表, 总数)
        """
        count_q = select(func.count()).where(
            GeneralAgents.user_id == user_id,
            GeneralAgents.status != 9,
        )
        total = (await db.execute(count_q)).scalar() or 0

        q = (
            select(GeneralAgents)
            .where(GeneralAgents.user_id == user_id, GeneralAgents.status != 9)
            .order_by(GeneralAgents.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def update(
        db: AsyncSession,
        agent: GeneralAgents,
        **kwargs,
    ) -> GeneralAgents:
        """更新字段（仅更新传入的非 None 值），只 flush 不 commit"""
        for key, value in kwargs.items():
            if value is not None:
                setattr(agent, key, value)
        await db.flush()
        return agent

    @staticmethod
    async def soft_delete(db: AsyncSession, agent: GeneralAgents) -> None:
        """软删除：status → 9，只 flush 不 commit"""
        agent.status = 9
        await db.flush()

    @staticmethod
    async def batch_update_status(
        db: AsyncSession,
        user_id: UUID,
        ids: list[UUID],
        status: int,
    ) -> int:
        """批量更新状态（仅属于该用户且未删除），返回实际更新行数"""
        from sqlalchemy import update as _update

        stmt = (
            _update(GeneralAgents)
            .where(
                GeneralAgents.id.in_(ids),
                GeneralAgents.user_id == user_id,
                GeneralAgents.status != 9,
            )
            .values(status=status)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    @staticmethod
    async def find_by_model_config(
        db: AsyncSession,
        config_id: UUID,
    ) -> list[GeneralAgents]:
        """
        查找使用指定 LLM 配置的综合 Agent（仅未删除）

        软删除记录不拦截配置删除（FK 为 ON DELETE SET NULL，自动置空）
        """
        q = select(GeneralAgents).where(
            GeneralAgents.llm_config_id == config_id,
            GeneralAgents.status != 9,
        )
        result = await db.execute(q)
        return list(result.scalars().all())
