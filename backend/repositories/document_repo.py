"""
文档数据访问

所有方法接收外部传入的 AsyncSession，不自行管理事务边界。
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Documents


class DocumentRepo:
    """文档 CRUD —— 只写 SQL，不管业务规则"""

    @staticmethod
    async def create(
        db: AsyncSession,
        knowledge_base_id: UUID,
        user_id: UUID,
        filename: str,
        file_path: str,
        file_size: int,
        file_type: str | None,
    ) -> Documents:
        """
        创建文档记录

        只做 insert + flush，不 commit
        返回带 id 的 ORM 对象
        """
        doc = Documents(
            knowledge_base_id=knowledge_base_id,
            user_id=user_id,
            filename=filename,
            file_path=file_path,
            file_size=file_size,
            file_type=file_type,
        )
        db.add(doc)
        await db.flush()
        return doc

    @staticmethod
    async def get_by_id(db: AsyncSession, doc_id: UUID) -> Documents | None:
        """
        按主键查询单条

        不做状态过滤（调用方自行判断 status）
        """
        return await db.get(Documents, doc_id)

    @staticmethod
    async def list_by_kb(
        db: AsyncSession,
        kb_id: UUID,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Documents], int]:
        """
        按知识库分页查询文档列表

        自动过滤 status=9（逻辑删除），按创建时间倒序
        返回 (列表, 总数)
        """
        # 总数
        count_q = select(func.count()).where(
            Documents.knowledge_base_id == kb_id,
            Documents.status != 9,
        )
        total = (await db.execute(count_q)).scalar() or 0

        # 分页数据
        q = (
            select(Documents)
            .where(Documents.knowledge_base_id == kb_id, Documents.status != 9)
            .order_by(Documents.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def soft_delete(db: AsyncSession, doc: Documents) -> None:
        """
        软删除：status → 9

        只 flush 不 commit
        """
        doc.status = 9
        await db.flush()

    @staticmethod
    async def soft_delete_by_kb(db: AsyncSession, kb_id: UUID) -> int:
        """
        软删除知识库下所有文件（status → 9）
        返回更新行数
        """
        from sqlalchemy import update as _update

        stmt = (
            _update(Documents)
            .where(
                Documents.knowledge_base_id == kb_id,
                Documents.status != 9,
            )
            .values(status=9)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    @staticmethod
    async def batch_soft_delete(
        db: AsyncSession,
        kb_id: UUID,
        user_id: UUID,
        ids: list[UUID],
    ) -> int:
        """
        批量软删除文档

        仅删除属于该用户、该知识库且未删除的记录，返回实际更新行数
        """
        from sqlalchemy import update as _update

        stmt = (
            _update(Documents)
            .where(
                Documents.id.in_(ids),
                Documents.knowledge_base_id == kb_id,
                Documents.user_id == user_id,
                Documents.status != 9,
            )
            .values(status=9)
        )
        result = await db.execute(stmt)
        await db.flush()
        return result.rowcount

    @staticmethod
    async def search_chunks(
        db: AsyncSession,
        kb_id: UUID,
        query_vec: list[float],
        top_k: int,
    ) -> list[dict]:
        """
        RAG 向量检索：按余弦相似度查知识库中与 query_vec 最相近的分块

        score = 1 - cosine_distance，越大越相似
        仅检索启用状态（e.status=1, c.status=1）的分块
        返回 [{chunk_id, content, filename, score}, ...]，按相似度降序
        """
        from backend.models import Chunks, Documents, Embeddings

        q = (
            select(
                Chunks.id.label("chunk_id"),
                Chunks.content,
                Documents.filename,
                (1 - Embeddings.embedding.cosine_distance(query_vec)).label("score"),
            )
            .join(Embeddings, Embeddings.chunk_id == Chunks.id)
            .join(Documents, Documents.id == Chunks.document_id)
            .where(
                Embeddings.kb_id == kb_id,
                Embeddings.status == 1,
                Chunks.status == 1,
            )
            .order_by(Embeddings.embedding.cosine_distance(query_vec))
            .limit(top_k)
        )
        rows = (await db.execute(q)).all()
        return [
            {
                "chunk_id": r.chunk_id,
                "content": r.content,
                "filename": r.filename,
                "score": float(r.score),
            }
            for r in rows
        ]
