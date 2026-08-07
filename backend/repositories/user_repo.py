"""
用户表数据访问

所有方法接收外部传入的 AsyncSession，不自行管理事务。
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users


class UserRepo:
    """用户相关数据库操作"""

    @staticmethod
    async def get_by_username(db: AsyncSession, username: str) -> Users | None:
        result = await db.execute(
            select(Users).where(User.username == username)
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def get_by_id(db: AsyncSession, user_id: UUID | str) -> Users | None:
        return await db.get(Users, user_id)
