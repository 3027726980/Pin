"""
Agent 数据访问

所有方法接收外部传入的 AsyncSession，不自行管理事务边界。
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Agents


class AgentRepo:
    """Agent CRUD —— 只写 SQL，不管业务规则"""

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
    ) -> Agents:
        """
        创建 Agent 记录

        只做 insert + flush，不 commit（由调用方控制事务）
        返回带 id 的 ORM 对象
        """
        agent = Agents(
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
    async def get_by_id(db: AsyncSession, agent_id: UUID) -> Agents | None:
        """
        按主键查询单条

        不做状态过滤（调用方自行判断 status）
        """
        return await db.get(Agents, agent_id)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Agents], int]:
        """
        按用户分页查询 Agent 列表

        自动过滤 status=9（逻辑删除），按创建时间倒序
        返回 (列表, 总数)
        """
        count_q = select(func.count()).where(
            Agents.user_id == user_id,
            Agents.status != 9,
        )
        total = (await db.execute(count_q)).scalar() or 0

        q = (
            select(Agents)
            .where(Agents.user_id == user_id, Agents.status != 9)
            .order_by(Agents.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def update(
        db: AsyncSession,
        agent: Agents,
        **kwargs,
    ) -> Agents:
        """
        更新 Agent 字段

        仅更新传入的非 None 值，None 字段保持原值
        只 flush 不 commit
        """
        for key, value in kwargs.items():
            if value is not None:
                setattr(agent, key, value)
        await db.flush()
        return agent

    @staticmethod
    async def soft_delete(db: AsyncSession, agent: Agents) -> None:
        """
        软删除：status → 9

        只 flush 不 commit
        """
        agent.status = 9
        await db.flush()

    @staticmethod
    async def batch_update_status(
        db: AsyncSession,
        user_id: UUID,
        ids: list[UUID],
        status: int,
    ) -> int:
        """
        批量更新 Agent 状态

        仅更新属于该用户且未删除的记录，返回实际更新行数
        """
        from sqlalchemy import update as _update

        stmt = (
            _update(Agents)
            .where(
                Agents.id.in_(ids),
                Agents.user_id == user_id,
                Agents.status != 9,
            )
            .values(status=status)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount
