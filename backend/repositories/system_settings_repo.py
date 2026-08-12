"""系统设置数据访问 —— 只写 SQL，不管业务规则"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import SystemSettings


class SystemSettingsRepo:
    """system_settings 表 CRUD"""

    @staticmethod
    async def get_by_key(db: AsyncSession, key: str) -> SystemSettings | None:
        """按 key 查询"""
        return (await db.execute(
            select(SystemSettings).where(SystemSettings.key == key))).scalar_one_or_none()

    @staticmethod
    async def list_all(db: AsyncSession) -> list[SystemSettings]:
        """全部设置项"""
        return list((await db.execute(select(SystemSettings))).scalars().all())

    @staticmethod
    async def upsert(db: AsyncSession, key: str, value: dict,
                     description: str | None = None) -> SystemSettings:
        """插入或更新（key 冲突则覆盖 value/description）"""
        from sqlalchemy.dialects.postgresql import insert

        stmt = (insert(SystemSettings)
                .values(key=key, value=value, description=description)
                .on_conflict_do_update(
                    index_elements=["key"],
                    set_={"value": value, "description": description})
                .returning(SystemSettings))
        return (await db.execute(stmt)).scalar_one()
