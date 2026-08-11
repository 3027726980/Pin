"""Agent 嵌入密钥数据访问 —— 只写 SQL，不管业务规则"""
from uuid import UUID

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AgentApiKeys


class AgentApiKeyRepo:
    """agent_api_keys 表 CRUD"""

    @staticmethod
    async def create(db: AsyncSession, agent_id: UUID, key_hash: str,
                     key_preview: str | None = None,
                     name: str | None = None) -> AgentApiKeys:
        """创建密钥记录(flush 不 commit)"""
        key = AgentApiKeys(agent_id=agent_id, key_hash=key_hash,
                           key_preview=key_preview, name=name)
        db.add(key)
        await db.flush()
        return key

    @staticmethod
    async def get_by_id(db: AsyncSession, key_id: UUID) -> AgentApiKeys | None:
        """按主键查询"""
        return await db.get(AgentApiKeys, key_id)

    @staticmethod
    async def get_by_hash(db: AsyncSession, key_hash: str) -> AgentApiKeys | None:
        """按哈希查询(鉴权用)"""
        q = select(AgentApiKeys).where(AgentApiKeys.key_hash == key_hash)
        return (await db.execute(q)).scalar_one_or_none()

    @staticmethod
    async def list_by_agent(db: AsyncSession, agent_id: UUID) -> list[AgentApiKeys]:
        """Agent 下的密钥列表(创建时间倒序)"""
        q = (select(AgentApiKeys)
             .where(AgentApiKeys.agent_id == agent_id)
             .order_by(AgentApiKeys.created_at.desc()))
        return list((await db.execute(q)).scalars().all())

    @staticmethod
    async def soft_delete(db: AsyncSession, key: AgentApiKeys) -> None:
        """物理删除(密钥无被引用方，直接删)"""
        await db.delete(key)
        await db.flush()

    @staticmethod
    async def update(db: AsyncSession, key: AgentApiKeys,
                     name: str | None = None,
                     enabled: int | None = None) -> None:
        """更新备注/启停状态"""
        if name is not None:
            key.name = name
        if enabled is not None:
            key.enabled = enabled
        await db.flush()

    @staticmethod
    async def touch_used_at(db: AsyncSession, key_id: UUID) -> None:
        """更新最后使用时间(公开接口鉴权成功后调用)"""
        await db.execute(
            update(AgentApiKeys)
            .where(AgentApiKeys.id == key_id)
            .values(last_used_at=func.now()))
        await db.flush()
