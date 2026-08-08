"""
知识库数据访问

所有方法接收外部传入的 AsyncSession，不自行管理事务边界。
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import KnowledgeBases


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
        chunk_size: int = 800,
        chunk_overlap: int = 150,
        chunk_separators: str = "\n##,\n###,\n,。,., ",
        embedding_model: str = "bge-small-zh-v1.5",
        embedding_dimension: int = 4096,
        user_model_config_id: UUID | None = None,
    ) -> KnowledgeBases:
        """
        创建知识库记录

        只做 insert + flush，不 commit（由调用方控制事务）
        返回带 id 的 ORM 对象
        """
        kb = KnowledgeBases(
            user_id=user_id,
            name=name,
            description=description,
            allowed_extensions=allowed_extensions,
            max_file_size=max_file_size,
            allow_multiple=allow_multiple,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            chunk_separators=chunk_separators,
            embedding_model=embedding_model,
            embedding_dimension=embedding_dimension,
            user_model_config_id=user_model_config_id,
        )
        db.add(kb)
        await db.flush()
        return kb

    @staticmethod
    async def get_by_id(db: AsyncSession, kb_id: UUID) -> KnowledgeBases | None:
        """
        按主键查询单条

        不做状态过滤（调用方自行判断 status）
        """
        return await db.get(KnowledgeBases, kb_id)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[KnowledgeBases], int]:
        """
        按用户分页查询知识库列表

        自动过滤 status=9（逻辑删除），按创建时间倒序
        返回 (列表, 总数)
        """
        # 总数
        count_q = select(func.count()).where(
            KnowledgeBases.user_id == user_id,
            KnowledgeBases.status != 9,
        )
        total = (await db.execute(count_q)).scalar() or 0

        # 分页数据
        q = (
            select(KnowledgeBases)
            .where(KnowledgeBases.user_id == user_id, KnowledgeBases.status != 9)
            .order_by(KnowledgeBases.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def update(
        db: AsyncSession,
        kb: KnowledgeBases,
        **kwargs,
    ) -> KnowledgeBases:
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
    async def soft_delete(db: AsyncSession, kb: KnowledgeBases) -> None:
        """
        软删除：status → 9

        只 flush 不 commit
        """
        kb.status = 9
        await db.flush()

    @staticmethod
    async def batch_update_status(
        db: AsyncSession,
        user_id: UUID,
        ids: list[UUID],
        status: int,
    ) -> int:
        """
        批量更新知识库状态

        仅更新属于该用户且未删除的记录，返回实际更新行数
        """
        from sqlalchemy import update as _update

        stmt = (
            _update(KnowledgeBases)
            .where(
                KnowledgeBases.id.in_(ids),
                KnowledgeBases.user_id == user_id,
                KnowledgeBases.status != 9,
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
    ) -> list[KnowledgeBases]:
        """
        查找使用指定模型配置的知识库（仅未删除）

        软删除记录不拦截配置删除（FK 为 ON DELETE SET NULL，自动置空）
        """
        q = select(KnowledgeBases).where(
            KnowledgeBases.user_model_config_id == config_id,
            KnowledgeBases.status != 9,
        )
        result = await db.execute(q)
        return list(result.scalars().all())
