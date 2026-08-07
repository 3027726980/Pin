"""
文档处理服务：解析 → 分块 → 向量化
"""
import logging
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.core.config import settings
from backend.models import Chunks, Documents, Embeddings, KnowledgeBases, UserModelConfig, Users
from backend.repositories import DocumentRepo, KnowledgeBaseRepo
from backend.services.knowledge import UPLOAD_ROOT
from backend.services.parsers import get_parser
from backend.services.embedding import EmbeddingService

logger = logging.getLogger(__name__)


class DocumentProcessService:
    """文档处理：解析 / 分块 / 向量化"""

    # ═══════════════════════════════════════════════
    # 解析
    # ═══════════════════════════════════════════════

    @staticmethod
    async def parse_documents(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_ids: list[UUID],
    ) -> int:
        """
        解析文档文本，存入 documents.content

        返回成功解析的文档数
        """
        count = 0
        for doc_id in doc_ids:
            doc = await DocumentRepo.get_by_id(db, doc_id)
            if doc is None or doc.status == 9:
                continue

            doc.is_parsed = 2
            try:
                parser = get_parser(doc.file_type or "")
                file_path = Path(UPLOAD_ROOT) / doc.file_path.lstrip("/")
                doc.content = parser.parse(str(file_path))
                doc.is_parsed = 1
                count += 1
            except Exception as e:
                logger.error(f"解析文档 {doc.filename} 失败: {e}")
                doc.is_parsed = -1
                continue

        await db.flush()
        return count

    # ═══════════════════════════════════════════════
    # 分块
    # ═══════════════════════════════════════════════

    @staticmethod
    async def chunk_documents(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_ids: list[UUID],
    ) -> int:
        """
        对已解析的文档文本进行分块

        流程：读取 doc.content 完整文本 → 递归分块 → 替换旧 chunks → 插入新行
        返回成功分块的文档数
        """
        separator_list = [s.strip() for s in kb.chunk_separators.split(",") if s.strip()]
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
            separators=separator_list,
            keep_separator=True,
        )

        success_count = 0
        for doc_id in doc_ids:
            doc = await DocumentRepo.get_by_id(db, doc_id)
            if doc is None or doc.status == 9:
                continue

            # 取完整文本
            if not doc.content:
                continue

            doc.is_chunked = 2
            try:
                texts = splitter.split_text(doc.content)

                # 先删 embeddings（FK 依赖），再删旧 chunks
                old_chunks = (await db.execute(
                    select(Chunks.id).where(Chunks.document_id == doc_id)
                )).scalars().all()
                if old_chunks:
                    await db.execute(delete(Embeddings).where(Embeddings.chunk_id.in_(old_chunks)))
                await db.execute(delete(Chunks).where(Chunks.document_id == doc_id))

                for i, text in enumerate(texts):
                    chunk = Chunks(
                        document_id=doc_id,
                        kb_id=kb.id,
                        chunk_index=i,
                        content=text,
                        chunk_metadata={
                            "source": doc.filename,
                            "chunk_index": i,
                            "total_chunks": len(texts),
                        },
                        status=1,
                    )
                    db.add(chunk)
                doc.is_chunked = 1
                success_count += 1
            except Exception as e:
                logger.error(f"文档 {doc.filename} 分块失败: {e}")
                doc.is_chunked = -1
                continue

        await db.flush()
        return success_count

    # ═══════════════════════════════════════════════
    # 向量化
    # ═══════════════════════════════════════════════

    @staticmethod
    async def vectorize_documents(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_ids: list[UUID],
    ) -> int:
        """对指定文档的所有分块进行向量化（含失败重试），返回成功处理的文档数"""
        q = select(Chunks).options(selectinload(Chunks.document)).where(
            Chunks.document_id.in_(doc_ids),
            Chunks.kb_id == kb.id,
            Chunks.status == 1,  # 仅启用的分块
        )
        result = await db.execute(q)
        chunks = list(result.scalars().all())
        if not chunks:
            return 0
        chunk_count = await DocumentProcessService._do_vectorize(db, kb, chunks)
        # 统计至少有一个 chunk 向量化成功的文档数
        success_doc_ids = {c.document_id for c in chunks if c.is_vectorized == 1}
        return len(success_doc_ids)

    @staticmethod
    async def vectorize_chunks(
        db: AsyncSession,
        kb: KnowledgeBases,
        chunk_ids: list[UUID],
    ) -> int:
        """对指定分块进行向量化"""
        q = select(Chunks).options(selectinload(Chunks.document)).where(
            Chunks.id.in_(chunk_ids),
            Chunks.kb_id == kb.id,
        )
        result = await db.execute(q)
        valid = [c for c in result.scalars().all() if c.content]
        if not valid:
            return 0
        return await DocumentProcessService._do_vectorize(db, kb, valid)

    @staticmethod
    async def _do_vectorize(
        db: AsyncSession,
        kb: KnowledgeBases,
        chunks: list[Chunks],
    ) -> int:
        """内部：对给定的 chunk 列表执行向量化，返回成功数"""
        if not kb.user_model_config_id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")
        cfg = await db.get(UserModelConfig, kb.user_model_config_id)
        if cfg is None:
            raise HTTPException(status_code=400, detail="关联的 Embedding 模型配置不存在")
        provider = cfg.provider
        model_name = cfg.model_name
        api_key = cfg.api_key
        url = cfg.base_url

        max_dim = settings.embedding.max_dimension
        batch_size = settings.embedding.batch_size
        count = 0

        # 先标记所有相关 chunk 为"进行中"
        for c in chunks:
            c.is_vectorized = 2
            c.document.is_vectorized = 2
        await db.flush()

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.content for c in batch]

            try:
                vectors = EmbeddingService.embed(
                    provider=provider,
                    model_name=model_name,
                    api_key=api_key,
                    base_url=url,
                    texts=texts,
                )
            except Exception as e:
                logger.error(f"第 {i // batch_size + 1} 批向量化失败: {e}")
                for c in batch:
                    c.is_vectorized = -1
                    c.document.is_vectorized = -1
                await db.flush()
                continue

            for chunk, vec in zip(batch, vectors):
                if len(vec) < max_dim:
                    vec = list(vec) + [0.0] * (max_dim - len(vec))

                await db.execute(delete(Embeddings).where(Embeddings.chunk_id == chunk.id))
                emb = Embeddings(
                    chunk_id=chunk.id,
                    kb_id=kb.id,
                    embedding=vec,
                    status=1,  # 与 chunk 状态同步，启用
                )
                db.add(emb)
                chunk.is_vectorized = 1
                chunk.document.is_vectorized = 1
                count += 1

        await db.flush()
        return count
