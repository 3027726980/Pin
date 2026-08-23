"""
用户自定义厂商 数据访问
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import UserProviders


class ProviderRepo:
    """user_providers 表 CRUD"""

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        name: str,
        protocol: str = "openai",
        base_url: str | None = None,
        description: str | None = None,
    ) -> UserProviders:
        """创建自定义厂商（只 flush 不 commit）"""
        p = UserProviders(user_id=user_id, name=name, protocol=protocol,
                          base_url=base_url, description=description)
        db.add(p)
        await db.flush()
        return p

    @staticmethod
    async def get_by_id(db: AsyncSession, provider_id: UUID) -> UserProviders | None:
        """按主键查询（不做归属过滤，调用方自行判断）"""
        return await db.get(UserProviders, provider_id)

    @staticmethod
    async def get_by_name(db: AsyncSession, user_id: UUID, name: str) -> UserProviders | None:
        """按 用户+名称 查询（唯一约束冲突检测）"""
        q = select(UserProviders).where(
            UserProviders.user_id == user_id,
            UserProviders.name == name,
        )
        result = await db.execute(q)
        return result.scalars().first()

    @staticmethod
    async def list_by_user(db: AsyncSession, user_id: UUID) -> list[UserProviders]:
        """当前用户的自定义厂商列表"""
        q = (
            select(UserProviders)
            .where(UserProviders.user_id == user_id)
            .order_by(UserProviders.created_at.desc())
        )
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def update(
        db: AsyncSession,
        provider: UserProviders,
        **kwargs,
    ) -> UserProviders:
        """更新字段（仅更新传入的非 None 值），只 flush 不 commit"""
        for key, value in kwargs.items():
            if value is not None:
                setattr(provider, key, value)
        await db.flush()
        return provider

    @staticmethod
    async def delete(db: AsyncSession, provider: UserProviders) -> None:
        """物理删除（只 flush 不 commit）"""
        await db.delete(provider)
        await db.flush()
