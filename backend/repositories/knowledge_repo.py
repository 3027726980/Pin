"""
知识库数据访问

所有方法接收外部传入的 AsyncSession，不自行管理事务边界。
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import KnowledgeBase


class KnowledgeBaseRepo:
    """知识库 CRUD —— 只写 SQL，不管业务规则"""

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        name: str,
        description: str | None,
        allowed_extensions: str | None,
        max_file_size: int,
        allow_multiple: bool,
    ) -> KnowledgeBase:
        """
        创建知识库记录

        只做 insert + flush，不 commit（由调用方控制事务）
        返回带 id 的 ORM 对象
        """
        kb = KnowledgeBase(
            user_id=user_id,
            name=name,
            description=description,
            allowed_extensions=allowed_extensions,
            max_file_size=max_file_size,
            allow_multiple=allow_multiple,
        )
        db.add(kb)
        await db.flush()
        return kb

    @staticmethod
    async def get_by_id(db: AsyncSession, kb_id: UUID) -> KnowledgeBase | None:
        """
        按主键查询单条

        不做状态过滤（调用方自行判断 status）
        """
        return await db.get(KnowledgeBase, kb_id)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[KnowledgeBase], int]:
        """
        按用户分页查询知识库列表

        自动过滤 status=9（逻辑删除），按创建时间倒序
        返回 (列表, 总数)
        """
        # 总数
        count_q = select(func.count()).where(
            KnowledgeBase.user_id == user_id,
            KnowledgeBase.status != 9,
        )
        total = (await db.execute(count_q)).scalar() or 0

        # 分页数据
        q = (
            select(KnowledgeBase)
            .where(KnowledgeBase.user_id == user_id, KnowledgeBase.status != 9)
            .order_by(KnowledgeBase.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def update(
        db: AsyncSession,
        kb: KnowledgeBase,
        **kwargs,
    ) -> KnowledgeBase:
        """
        更新知识库字段

        仅更新传入的非 None 值，None 字段保持原值
        只 flush 不 commit
        """
        for key, value in kwargs.items():
            if value is not None:
                setattr(kb, key, value)
        await db.flush()
        return kb

    @staticmethod
    async def soft_delete(db: AsyncSession, kb: KnowledgeBase) -> None:
        """
        软删除：status → 9

        只 flush 不 commit
        """
        kb.status = 9
        await db.flush()
