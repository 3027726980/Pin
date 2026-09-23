"""
文档处理服务：解析 → 清洗 → 分块 → 向量化 + 上传自动处理后台任务
"""
import asyncio
import functools
import logging
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.core.config import settings
from backend.core.constants import UPLOAD_ROOT
from backend.core.database import async_session_local
from backend.models import Chunks, Documents, Embeddings, KnowledgeBases, UserModelConfig, Users
from backend.repositories import DocumentRepo, KnowledgeBaseRepo
from backend.schemas.knowledge import (
    DocumentPreview,
    DocumentPreviewSource,
    PreviewChunk,
    ProcessingConfig,
)
from backend.services.document_cleaning import clean_text, cleaning_hash
from backend.services.embedding import EmbeddingService
from backend.services.parsers import get_parser
from backend.services.processing_strategy import (
    PROCESSING_ALGORITHM_VERSION,
    effective_processing_config,
    processing_config_hash,
)
from backend.services.system_settings import SystemSettingsService

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TextChunk:
    """一段最终可展示或持久化的文本切片及其与前片的真实重叠长度。"""

    content: str
    overlap_char_count: int = 0


class DocumentProcessService:
    """文档处理：解析 / 清洗 / 分块 / 向量化"""

    # ═══════════════════════════════════════════════
    # 解析
    # ═══════════════════════════════════════════════

    @staticmethod
    def _resolve_processing_config(
        kb: KnowledgeBases,
        doc: Documents,
        snapshot: ProcessingConfig | dict | None = None,
    ) -> ProcessingConfig:
        """优先使用任务快照，否则解析文档当前有效策略。"""
        if snapshot is not None:
            return ProcessingConfig.model_validate(snapshot)
        return effective_processing_config(kb, doc)

    @staticmethod
    async def get_preview_source(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_id: UUID,
    ) -> DocumentPreviewSource:
        """读取已有原文或临时解析原文件，返回前端预览源且不写数据库。"""
        doc = await DocumentRepo.get_by_id(db, doc_id)
        if doc is None or doc.status == 9 or doc.knowledge_base_id != kb.id:
            raise HTTPException(status_code=404, detail="文档不存在")
        try:
            if doc.content is not None:
                raw = doc.content
            else:
                parser = get_parser(doc.file_type or "")
                file_path = Path(UPLOAD_ROOT) / doc.file_path.lstrip("/")
                raw = await asyncio.to_thread(parser.parse, str(file_path))
        except Exception as exc:
            logger.error("读取文档 %s 预览源失败: %s", doc.filename, exc)
            raise HTTPException(status_code=400, detail=f"预览源解析失败: {exc}") from exc

        max_chars = int(getattr(settings.document, "preview_max_chars", 30000))
        truncated = len(raw) > max_chars
        warnings = (
            [f"当前仅预览前 {max_chars} 个字符；正式处理会使用完整文件"]
            if truncated else []
        )
        return DocumentPreviewSource(
            document_id=doc.id,
            filename=doc.filename,
            raw_content=raw[:max_chars],
            algorithm_version=PROCESSING_ALGORITHM_VERSION,
            truncated=truncated,
            warnings=warnings,
        )

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
            if doc.is_parsed == 2:  # 处理中保护：自动/手动并发时跳过重复触发
                continue

            doc.is_parsed = 2
            doc.last_error = None  # 重新处理开始，清空上次失败原因
            try:
                parser = get_parser(doc.file_type or "")
                file_path = Path(UPLOAD_ROOT) / doc.file_path.lstrip("/")
                parsed_content = await asyncio.to_thread(parser.parse, str(file_path))
                # PostgreSQL TEXT 无法表示 NUL；这是持久化边界的最小规范化，
                # 其余控制字符及业务清洗仍由 clean_documents 统一处理。
                doc.content = parsed_content.replace("\x00", "")
                doc.is_parsed = 1
                doc.cleaned_content = None
                doc.is_cleaned = 0
                doc.cleaning_config_hash = None
                doc.is_chunked = 0
                doc.is_vectorized = 0
                count += 1
            except Exception as e:
                logger.error(f"解析文档 {doc.filename} 失败: {e}")
                doc.is_parsed = -1
                doc.last_error = f"解析失败: {e}"
                continue

        await db.flush()
        return count

    @staticmethod
    def _split_text(kb: KnowledgeBases | ProcessingConfig, content: str) -> list[str]:
        """按知识库分块设置切分文本，返回最终片段内容。"""
        return [part.content for part in DocumentProcessService._split_text_with_overlap(kb, content)]

    @staticmethod
    def _split_text_with_overlap(
        kb: KnowledgeBases | ProcessingConfig,
        content: str,
    ) -> list[TextChunk]:
        """按有序分隔符贪心切主体，再强制保留相邻切片尾首重叠。"""
        chunk_size = max(1, int(kb.chunk_size))
        overlap = min(max(0, int(kb.chunk_overlap)), chunk_size - 1)
        body_size = max(1, chunk_size - overlap)
        separator_list = [s for s in kb.chunk_separators.split(",") if s != ""]
        bodies: list[str] = []
        position = 0
        while position < len(content):
            max_end = min(position + body_size, len(content))
            chosen_end = max_end
            if max_end < len(content):
                found_separator = False
                for separator in separator_list:
                    search_end = max_end
                    while search_end > position:
                        index = content.rfind(separator, position + 1, search_end)
                        if index < 0:
                            break
                        candidate = index + len(separator)
                        if candidate <= max_end:
                            chosen_end = candidate
                            found_separator = True
                            break
                        search_end = index
                    if found_separator:
                        break
            body = content[position:chosen_end]
            if body.strip():
                bodies.append(body)
            position = chosen_end

        parts: list[TextChunk] = []
        for body in bodies:
            if not parts or overlap == 0:
                parts.append(TextChunk(content=body))
                continue
            actual_overlap = min(overlap, len(parts[-1].content))
            parts.append(TextChunk(
                content=parts[-1].content[-actual_overlap:] + body,
                overlap_char_count=actual_overlap,
            ))
        return parts

    @staticmethod
    async def preview_document(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_id: UUID,
    ) -> DocumentPreview:
        """在内存中按知识库已保存策略解析、清洗和分块，不写入任何处理结果。"""
        doc = await DocumentRepo.get_by_id(db, doc_id)
        if doc is None or doc.status == 9 or doc.knowledge_base_id != kb.id:
            raise HTTPException(status_code=404, detail="文档不存在")

        try:
            parser = get_parser(doc.file_type or "")
            file_path = Path(UPLOAD_ROOT) / doc.file_path.lstrip("/")
            raw = await asyncio.to_thread(parser.parse, str(file_path))
            strategy = effective_processing_config(kb, doc)
            cleaned = clean_text(raw, strategy.cleaning_config)
            chunks = DocumentProcessService._split_text_with_overlap(strategy, cleaned)
        except Exception as exc:
            logger.error("预览文档 %s 失败: %s", doc.filename, exc)
            raise HTTPException(status_code=400, detail=f"预览失败: {exc}") from exc

        max_chars = int(getattr(settings.document, "preview_max_chars", 30000))
        max_chunks = int(getattr(settings.document, "preview_max_chunks", 100))
        warnings: list[str] = []
        if len(raw) > max_chars:
            warnings.append(f"原文已截断为前 {max_chars} 个字符")
        if len(cleaned) > max_chars:
            warnings.append(f"清洗文本已截断为前 {max_chars} 个字符")
        if len(chunks) > max_chunks:
            warnings.append(f"切片预览已截断为前 {max_chunks} 个片段")
        return DocumentPreview(
            document_id=doc.id,
            filename=doc.filename,
            raw_content=raw[:max_chars],
            cleaned_content=cleaned[:max_chars],
            chunks=[
                PreviewChunk(
                    index=index,
                    content=part.content,
                    char_count=len(part.content),
                    overlap_char_count=part.overlap_char_count,
                )
                for index, part in enumerate(chunks[:max_chunks])
            ],
            cleaning_config_hash=cleaning_hash(strategy.cleaning_config),
            warnings=warnings,
        )

    @staticmethod
    async def clean_documents(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_ids: list[UUID],
        processing_config: ProcessingConfig | dict | None = None,
    ) -> int:
        """将已解析原文按文档有效策略清洗并持久化。"""
        count = 0
        for doc_id in doc_ids:
            doc = await DocumentRepo.get_by_id(db, doc_id)
            if doc is None or doc.status == 9 or doc.knowledge_base_id != kb.id:
                continue
            if doc.is_cleaned == 2 or not doc.content:
                continue

            doc.is_cleaned = 2
            doc.last_error = None
            try:
                strategy = DocumentProcessService._resolve_processing_config(
                    kb, doc, processing_config
                )
                doc.cleaned_content = clean_text(doc.content, strategy.cleaning_config)
                doc.cleaning_config_hash = cleaning_hash(strategy.cleaning_config)
                doc.is_cleaned = 1
                count += 1
            except Exception as exc:
                logger.error("清洗文档 %s 失败: %s", doc.filename, exc)
                doc.is_cleaned = -1
                doc.last_error = f"清洗失败: {exc}"
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
        processing_config: ProcessingConfig | dict | None = None,
    ) -> int:
        """
        对已清洗的文档文本进行分块

        流程：读取 doc.cleaned_content 完整文本 → 递归分块 → 替换旧 chunks → 插入新行
        返回成功分块的文档数
        """
        success_count = 0
        for doc_id in doc_ids:
            doc = await DocumentRepo.get_by_id(db, doc_id)
            if doc is None or doc.status == 9:
                continue
            if doc.is_chunked == 2:  # 处理中保护：自动/手动并发时跳过重复触发
                continue

            # 取完整文本
            if doc.is_cleaned != 1 or not doc.cleaned_content:
                continue

            doc.is_chunked = 2
            doc.last_error = None  # 重新处理开始，清空上次失败原因
            try:
                strategy = DocumentProcessService._resolve_processing_config(
                    kb, doc, processing_config
                )
                parts = DocumentProcessService._split_text_with_overlap(
                    strategy, doc.cleaned_content
                )

                # 先删 embeddings（FK 依赖），再删旧 chunks
                old_chunks = (await db.execute(
                    select(Chunks.id).where(Chunks.document_id == doc_id)
                )).scalars().all()
                if old_chunks:
                    await db.execute(delete(Embeddings).where(Embeddings.chunk_id.in_(old_chunks)))
                await db.execute(delete(Chunks).where(Chunks.document_id == doc_id))

                for i, part in enumerate(parts):
                    chunk = Chunks(
                        document_id=doc_id,
                        kb_id=kb.id,
                        chunk_index=i,
                        content=part.content,
                        chunk_metadata={
                            "source": doc.filename,
                            "chunk_index": i,
                            "total_chunks": len(parts),
                            "overlap_char_count": part.overlap_char_count,
                        },
                        status=1,
                    )
                    db.add(chunk)
                doc.is_chunked = 1
                doc.applied_processing_config_hash = processing_config_hash(strategy)
                doc.applied_algorithm_version = PROCESSING_ALGORITHM_VERSION
                success_count += 1
            except Exception as e:
                logger.error(f"文档 {doc.filename} 分块失败: {e}")
                doc.is_chunked = -1
                doc.last_error = f"分块失败: {e}"
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
                # 同步 embed（本地 torch 推理 / 同步 HTTP）扔进线程池执行：
                # 同步直调会冻结事件循环（卡住期间所有请求与 SSE 流停摆；
                # 线程在等待 I/O/内核计算时释放 GIL，循环不受影响）
                vectors = await asyncio.get_running_loop().run_in_executor(
                    None,
                    functools.partial(
                        EmbeddingService.embed,
                        provider=provider,
                        model_name=model_name,
                        api_key=api_key,
                        base_url=url,
                        texts=texts,
                        protocol=cfg.protocol,
                    ),
                )
            except Exception as e:
                logger.error(f"第 {i // batch_size + 1} 批向量化失败: {e}")
                for c in batch:
                    c.is_vectorized = -1
                    c.document.is_vectorized = -1
                    c.document.last_error = f"向量化失败: {e}"
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

        # 全部成功才清空失败原因（部分失败保留错误信息便于排查）
        if all(c.is_vectorized == 1 for c in chunks):
            for c in chunks:
                c.document.last_error = None
        await db.flush()
        return count

    # ═══════════════════════════════════════════════
    # 一键全链路处理 / 上传后台任务
    # ═══════════════════════════════════════════════

    @staticmethod
    async def process_document(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_id: UUID,
        processing_config: ProcessingConfig | dict | None = None,
    ) -> bool:
        """执行解析、清洗、分块和向量化，并在成功后原子替换旧的可检索切片。"""
        doc = await DocumentRepo.get_by_id(db, doc_id)
        if doc is None or doc.status == 9 or doc.knowledge_base_id != kb.id:
            return False
        strategy = DocumentProcessService._resolve_processing_config(
            kb, doc, processing_config
        )

        # 清除排队标记或此前处理的瞬态状态；原有 chunks/embeddings 保持可检索，
        # 直到新切片和向量全部生成成功。
        doc.is_parsed = 0
        doc.is_cleaned = 0
        doc.is_chunked = 0
        doc.is_vectorized = 0
        doc.last_error = None
        await db.flush()

        await DocumentProcessService.parse_documents(db, kb, [doc_id])
        if doc.is_parsed != 1:
            return False
        await DocumentProcessService.clean_documents(db, kb, [doc_id], strategy)
        if doc.is_cleaned != 1 or not doc.cleaned_content:
            return False

        doc.is_chunked = 2
        try:
            parts = DocumentProcessService._split_text_with_overlap(
                strategy, doc.cleaned_content
            )
            if not parts:
                raise ValueError("清洗后的文本为空，无法切片")
            staged_chunks = [
                Chunks(
                    document_id=doc.id,
                    kb_id=kb.id,
                    chunk_index=index,
                    content=part.content,
                    chunk_metadata={
                        "source": doc.filename,
                        "chunk_index": index,
                        "total_chunks": len(parts),
                        "overlap_char_count": part.overlap_char_count,
                    },
                    status=0,
                    document=doc,
                )
                for index, part in enumerate(parts)
            ]
            db.add_all(staged_chunks)
            await db.flush()
        except Exception as exc:
            logger.error("文档 %s 一键分块失败: %s", doc.filename, exc)
            doc.is_chunked = -1
            doc.last_error = f"分块失败: {exc}"
            await db.flush()
            return False

        vectorized = await DocumentProcessService._do_vectorize(db, kb, staged_chunks)
        if vectorized != len(staged_chunks) or any(
            chunk.is_vectorized != 1 for chunk in staged_chunks
        ):
            staged_ids = [chunk.id for chunk in staged_chunks]
            await db.execute(delete(Embeddings).where(Embeddings.chunk_id.in_(staged_ids)))
            await db.execute(delete(Chunks).where(Chunks.id.in_(staged_ids)))
            doc.is_chunked = -1
            doc.is_vectorized = -1
            doc.last_error = doc.last_error or "向量化失败，已保留旧切片"
            await db.flush()
            return False

        staged_ids = [chunk.id for chunk in staged_chunks]
        old_ids = (await db.execute(
            select(Chunks.id).where(
                Chunks.document_id == doc.id,
                ~Chunks.id.in_(staged_ids),
            )
        )).scalars().all()
        if old_ids:
            await db.execute(delete(Embeddings).where(Embeddings.chunk_id.in_(old_ids)))
            await db.execute(delete(Chunks).where(Chunks.id.in_(old_ids)))
        for chunk in staged_chunks:
            chunk.status = 1
        doc.is_chunked = 1
        doc.is_vectorized = 1
        doc.applied_processing_config_hash = processing_config_hash(strategy)
        doc.applied_algorithm_version = PROCESSING_ALGORITHM_VERSION
        doc.last_error = None
        await db.flush()
        return True

    @staticmethod
    async def process_document_to_stage(
        db: AsyncSession,
        kb: KnowledgeBases,
        doc_id: UUID,
        target_stage: str,
        processing_config: ProcessingConfig | dict | None = None,
    ) -> bool:
        """处理到指定阶段，并在服务端重跑所需的前置阶段。"""
        if target_stage not in {"parse", "clean", "chunk", "vectorize"}:
            raise ValueError(f"未知处理目标阶段: {target_stage}")
        if target_stage == "vectorize":
            return await DocumentProcessService.process_document(
                db, kb, doc_id, processing_config
            )

        doc = await DocumentRepo.get_by_id(db, doc_id)
        if doc is None or doc.status == 9 or doc.knowledge_base_id != kb.id:
            return False
        strategy = DocumentProcessService._resolve_processing_config(
            kb, doc, processing_config
        )
        doc.is_parsed = 0
        doc.is_cleaned = 0
        doc.is_chunked = 0
        doc.is_vectorized = 0
        doc.last_error = None
        await db.flush()

        await DocumentProcessService.parse_documents(db, kb, [doc_id])
        if doc.is_parsed != 1 or target_stage == "parse":
            return doc.is_parsed == 1
        await DocumentProcessService.clean_documents(db, kb, [doc_id], strategy)
        if doc.is_cleaned != 1 or target_stage == "clean":
            return doc.is_cleaned == 1
        await DocumentProcessService.chunk_documents(db, kb, [doc_id], strategy)
        return doc.is_chunked == 1

    _auto_process_slots: set[str] = set()  # 正在自动处理的 doc_id（进程内并发上限管理）
    _auto_process_lock = asyncio.Lock()

    @staticmethod
    async def auto_process_document(
        kb_id: str | UUID,
        doc_id: str | UUID,
        target_stage: str = "vectorize",
        processing_config: dict | None = None,
    ) -> None:
        """
        上传后自动处理后台任务：解析 → 清洗 → 分块 → 向量化 全链路

        - 独立 session（BackgroundTasks 执行时请求的 session 已关闭，必须自开）
        - 并发上限动态读 system_settings.document.max_concurrent（排队等待而非丢弃）
        - 每步失败短路后续（解析失败不分块、分块失败不向量化）
        - 知识库/文档已软删除时直接返回
        """
        kb_id = UUID(str(kb_id))
        doc_id = UUID(str(doc_id))

        # 等待可用槽位（动态读 max_concurrent，支持运行期调小后新任务按新值排队）
        while True:
            cfg = SystemSettingsService.get("document") or {}
            max_concurrent = int(cfg.get("max_concurrent", 2) or 2)
            async with DocumentProcessService._auto_process_lock:
                if len(DocumentProcessService._auto_process_slots) < max_concurrent:
                    DocumentProcessService._auto_process_slots.add(str(doc_id))
                    break
            await asyncio.sleep(0.5)

        try:
            async with async_session_local() as db:
                kb = await db.get(KnowledgeBases, kb_id)
                doc = await DocumentRepo.get_by_id(db, doc_id)
                # 任务排队期间知识库/文档可能已被删除（软删）→ 不处理
                if kb is None or doc is None or kb.status == 9 or doc.status == 9:
                    return

                # 处理到目标阶段；向量化档使用暂存切片，仅在成功后替换旧可检索数据。
                await DocumentProcessService.process_document_to_stage(
                    db, kb, doc_id, target_stage, processing_config
                )
                await db.commit()
        except Exception as e:  # 兜底：未预期异常不冒泡（BackgroundTasks 已返回响应）
            logger.error(f"自动处理文档 {doc_id} 未预期异常: {e}")
        finally:
            async with DocumentProcessService._auto_process_lock:
                DocumentProcessService._auto_process_slots.discard(str(doc_id))
