"""
文档处理服务：解析 → 分块 → 向量化
"""
import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from langchain_text_splitters import RecursiveCharacterTextSplitter

from backend.core.config import settings
from backend.models import Chunk, Document, Embedding, KnowledgeBase, ModelConfig, User
from backend.repositories import DocumentRepo, KnowledgeBaseRepo, ModelConfigRepo
from backend.services.parsers import get_parser

logger = logging.getLogger(__name__)


class DocumentProcessService:
    """文档处理：解析 / 分块 / 向量化"""

    # ═══════════════════════════════════════════════
    # 解析
    # ═══════════════════════════════════════════════

    @staticmethod
    async def parse_documents(
        db: AsyncSession,
        kb: KnowledgeBase,
        doc_ids: list[UUID],
    ) -> int:
        """
        解析文档文本，更新 document.status 和 document_texts

        返回成功解析的文档数
        """
        count = 0
        for doc_id in doc_ids:
            doc = await DocumentRepo.get_by_id(db, doc_id)
            if doc is None or doc.status == 9:
                continue

            try:
                parser = get_parser(doc.file_type or "")
                # 构建完整文件路径
                from pathlib import Path as _Path

                from backend.services.knowledge import UPLOAD_ROOT

                file_path = _Path(UPLOAD_ROOT) / doc.file_path.lstrip("/")
                text = parser.parse(str(file_path))

                # 将解析结果存入 chunks（暂不分块，后续单独处理）
                # 先清旧 chunk，插入单条完整文本作为 chunk_index=0
                from sqlalchemy import delete as _delete

                await db.execute(_delete(Chunk).where(Chunk.document_id == doc_id))
                chunk = Chunk(
                    document_id=doc_id,
                    kb_id=kb.id,
                    chunk_index=0,
                    content=text,
                    status=1,  # 已完成
                )
                db.add(chunk)
                count += 1
            except Exception as e:
                logger.error(f"解析文档 {doc_id} 失败: {e}")
                # 记录失败但继续处理其他
                continue

        await db.flush()
        return count

    # ═══════════════════════════════════════════════
    # 分块
    # ═══════════════════════════════════════════════

    @staticmethod
    async def chunk_documents(
        db: AsyncSession,
        kb: KnowledgeBase,
        doc_ids: list[UUID],
    ) -> int:
        """
        对已解析的文档文本进行分块

        流程：读取 chunks 中 chunk_index=0 的完整文本 → 分块 → 替换为多个 chunk 行
        返回生成的总块数
        """
        from sqlalchemy import select as _select

        separator_list = [s.strip() for s in kb.chunk_separators.split(",") if s.strip()]
        splitter = RecursiveCharacterTextSplitter(
            chunk_size=kb.chunk_size,
            chunk_overlap=kb.chunk_overlap,
            separators=separator_list,
            keep_separator=True,
        )

        total_chunks = 0
        for doc_id in doc_ids:
            doc = await DocumentRepo.get_by_id(db, doc_id)
            if doc is None or doc.status == 9:
                continue

            # 取完整文本（chunk_index=0）
            q = _select(Chunk).where(
                Chunk.document_id == doc_id,
                Chunk.chunk_index == 0,
                Chunk.status != -1,
            )
            result = await db.execute(q)
            full_chunk = result.scalar_one_or_none()
            if full_chunk is None:
                continue

            # 分块
            texts = splitter.split_text(full_chunk.content)

            # 删除旧块
            from sqlalchemy import delete as _delete

            await db.execute(_delete(Chunk).where(Chunk.document_id == doc_id))

            # 插入新块
            for i, text in enumerate(texts):
                chunk = Chunk(
                    document_id=doc_id,
                    kb_id=kb.id,
                    chunk_index=i,
                    content=text,
                    status=1,  # 已完成
                )
                db.add(chunk)
                total_chunks += 1

        await db.flush()
        return total_chunks

    # ═══════════════════════════════════════════════
    # 向量化
    # ═══════════════════════════════════════════════

    @staticmethod
    async def vectorize_chunks(
        db: AsyncSession,
        kb: KnowledgeBase,
        chunk_ids: list[UUID],
    ) -> int:
        """
        对指定分块进行向量化

        流程：取 chunk 文本 → Embedding API → 零填充 → 存 embeddings 表
        返回成功向量化的块数
        """
        from sqlalchemy import select as _select

        # 找 active 的 embedding 配置
        cfg_q = _select(ModelConfig).where(
            ModelConfig.user_id == kb.user_id,
            ModelConfig.model_type == 1,
            ModelConfig.is_active == True,
        )
        result = await db.execute(cfg_q)
        cfg = result.scalars().first()
        if cfg is None:
            raise HTTPException(status_code=400, detail="未找到启用的 Embedding 模型配置")

        from openai import AsyncOpenAI

        client = AsyncOpenAI(api_key=cfg.key_value)
        max_dim = settings.embedding.max_dimension

        count = 0
        for chunk_id in chunk_ids:
            chunk = await db.get(Chunk, chunk_id)
            if chunk is None:
                continue

            try:
                # 调 Embedding API
                resp = await client.embeddings.create(
                    model=cfg.model_name,
                    input=chunk.content,
                )
                vec = resp.data[0].embedding

                # 零填充
                if len(vec) < max_dim:
                    vec = list(vec) + [0.0] * (max_dim - len(vec))

                # 删除旧 embedding（如果存在）
                from sqlalchemy import delete as _delete

                await db.execute(_delete(Embedding).where(Embedding.chunk_id == chunk_id))

                emb = Embedding(
                    chunk_id=chunk_id,
                    kb_id=kb.id,
                    embedding=vec,
                    status=1,
                )
                db.add(emb)
                count += 1
            except Exception as e:
                logger.error(f"向量化 chunk {chunk_id} 失败: {e}")
                continue

        await db.flush()
        return count
