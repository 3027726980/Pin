"""
文档数据访问

所有方法接收外部传入的 AsyncSession，不自行管理事务边界。
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Chunks, Documents, Embeddings, KnowledgeBases


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

    # ═══════════════════════════════════════════════
    # 级联清理（删除知识库/文档时）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def soft_delete_chunks(db: AsyncSession, doc_ids: list[UUID]) -> None:
        """
        级联软删除文档的切片与向量（status → 9）

        先软删 embeddings（FK 依赖），再软删 chunks
        """
        from sqlalchemy import update as _update

        chunk_ids = (await db.execute(
            select(Chunks.id).where(
                Chunks.document_id.in_(doc_ids), Chunks.status != 9)
        )).scalars().all()
        if chunk_ids:
            await db.execute(_update(Embeddings).where(
                Embeddings.chunk_id.in_(chunk_ids), Embeddings.status != 9
            ).values(status=9))
        await db.execute(_update(Chunks).where(
            Chunks.document_id.in_(doc_ids), Chunks.status != 9
        ).values(status=9))
        await db.flush()

    @staticmethod
    async def soft_delete_chunks_by_kb(db: AsyncSession, kb_id: UUID) -> None:
        """
        级联软删除知识库下所有切片与向量（status → 9）
        """
        from sqlalchemy import update as _update

        chunk_ids = (await db.execute(
            select(Chunks.id).where(Chunks.kb_id == kb_id, Chunks.status != 9)
        )).scalars().all()
        if chunk_ids:
            await db.execute(_update(Embeddings).where(
                Embeddings.chunk_id.in_(chunk_ids), Embeddings.status != 9
            ).values(status=9))
        await db.execute(_update(Chunks).where(
            Chunks.kb_id == kb_id, Chunks.status != 9
        ).values(status=9))
        await db.flush()

    @staticmethod
    async def reset_stuck_processing(db: AsyncSession) -> int:
        """
        启动恢复：将卡在"处理中"（状态 2）的文档重置为 0（未处理）

        后台任务进程内执行、重启即丢失，防止状态永远卡死；返回重置行数
        """
        from sqlalchemy import or_, update as _update

        result = await db.execute(_update(Documents).where(
            or_(Documents.is_parsed == 2,
                Documents.is_chunked == 2,
                Documents.is_vectorized == 2),
            Documents.status != 9,
        ).values(is_parsed=0, is_chunked=0, is_vectorized=0))
        await db.flush()
        return result.rowcount

    @staticmethod
    async def list_processing_tasks(db: AsyncSession, user_id: UUID) -> list[dict]:
        """
        全局处理任务列表（处理浮窗用）

        查询当前用户所有"处理中/排队"（任一状态字段为 2）且未删除的文档，
        附带知识库名称；按更新时间倒序。返回 dict 列表，不含 SQL 对象。
        """
        from sqlalchemy import or_

        q = (
            select(
                Documents.id.label("doc_id"),
                Documents.filename,
                Documents.is_parsed,
                Documents.is_chunked,
                Documents.is_vectorized,
                KnowledgeBases.id.label("kb_id"),
                KnowledgeBases.name.label("kb_name"),
            )
            .join(KnowledgeBases, KnowledgeBases.id == Documents.knowledge_base_id)
            .where(
                Documents.user_id == user_id,
                Documents.status != 9,
                KnowledgeBases.status != 9,
                or_(Documents.is_parsed == 2,
                    Documents.is_chunked == 2,
                    Documents.is_vectorized == 2),
            )
            .order_by(Documents.updated_at.desc())
        )
        rows = (await db.execute(q)).all()
        return [
            {
                "doc_id": str(r.doc_id),
                "filename": r.filename,
                "kb_id": str(r.kb_id),
                "kb_name": r.kb_name,
                "is_parsed": r.is_parsed,
                "is_chunked": r.is_chunked,
                "is_vectorized": r.is_vectorized,
            }
            for r in rows
        ]
