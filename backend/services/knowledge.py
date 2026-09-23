"""
知识库 + 文档 业务逻辑

- 知识库 CRUD：创建 → 列表 → 详情 → 编辑 → 软删除
- 文件管理：上传校验（类型/大小）→ 写磁盘 → 入库 → 软删除
- 所有操作均校验：知识库归属当前用户 + 状态非删除
"""
import uuid as _uuid

from copy import deepcopy
from pathlib import Path as _Path
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.constants import UPLOAD_ROOT
from backend.models import Documents, KnowledgeBases, UserModelConfig, Users
from backend.repositories import DocumentRepo, KnowledgeBaseRepo, UserModelConfigRepo
from backend.schemas.knowledge import (
    DocumentListItem,
    DocumentProcessingStrategyUpdate,
    KnowledgeBaseCreate,
    KnowledgeBaseListItem,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    PaginatedResponse,
    StoredChunkItem,
)
from backend.schemas.cleaning import CleaningConfig
from backend.services.system_settings import SystemSettingsService
from backend.services.processing_strategy import (
    effective_processing_config,
    processing_config_hash,
)


def _document_list_item(
    kb: KnowledgeBases,
    doc: Documents,
    chunk_count: int,
) -> DocumentListItem:
    """将文档 ORM 对象补齐为包含策略状态的列表响应。"""
    effective_config = effective_processing_config(kb, doc)
    current_hash = processing_config_hash(effective_config)
    return DocumentListItem(
        id=doc.id,
        filename=doc.filename,
        file_size=doc.file_size,
        file_type=doc.file_type,
        status=doc.status,
        is_parsed=doc.is_parsed,
        is_cleaned=doc.is_cleaned,
        is_chunked=doc.is_chunked,
        is_vectorized=doc.is_vectorized,
        processing_config=doc.processing_config,
        strategy_mode="custom" if doc.processing_config is not None else "inherit",
        effective_processing_config=effective_config,
        strategy_outdated=(
            chunk_count > 0
            and (
                doc.applied_processing_config_hash is None
                or doc.applied_processing_config_hash != current_hash
            )
        ),
        applied_algorithm_version=doc.applied_algorithm_version,
        chunk_count=chunk_count,
        last_error=doc.last_error,
        created_at=doc.created_at,
    )


async def _ensure_model_config(
    db: AsyncSession, user_id: UUID, provider: str, model_name: str, dimension: int
) -> UserModelConfig:
    """查找或创建 user_model_config，确保知识库始终关联配置 ID"""
    from sqlalchemy import select as _select
    q = _select(UserModelConfig).where(
        UserModelConfig.user_id == user_id,
        UserModelConfig.provider == provider,
        UserModelConfig.model_name == model_name,
    )
    result = await db.execute(q)
    cfg = result.scalars().first()
    if cfg:
        return cfg
    cfg = await UserModelConfigRepo.create(
        db,
        user_id=user_id,
        provider=provider,
        model_name=model_name,
        model_type=1,
        base_url=None,
        api_key=None,
        dimension=dimension,
        is_active=True,
    )
    return cfg


class KnowledgeBaseService:
    """知识库 + 文件 业务逻辑 —— 不依赖 HTTP 请求/响应，只处理数据和规则"""

    # ═══════════════════════════════════════════════
    # 知识库 CRUD
    # ═══════════════════════════════════════════════

    @staticmethod
    def get_default_cleaning_config() -> dict:
        """读取、校验并深拷贝启动配置中的知识库默认清洗规则。"""
        default_cleaning = getattr(
            getattr(settings.document, "cleaning", None),
            "default_rules",
            {"rules": []},
        )
        source_config = (
            vars(default_cleaning)
            if hasattr(default_cleaning, "__dict__")
            else default_cleaning
        )
        CleaningConfig.model_validate(source_config)
        return deepcopy(source_config)

    @staticmethod
    def get_default_auto_process() -> bool:
        """读取当前系统设置中新建知识库的自动处理默认值。"""
        document_config = SystemSettingsService.get("document") or {}
        configured_default = getattr(settings.document, "default_auto_process", False)
        return bool(
            document_config.get(
                "default_auto_process",
                document_config.get("auto_process", configured_default),
            )
        )

    @staticmethod
    async def create(
        db: AsyncSession,
        user: Users,
        data: KnowledgeBaseCreate,
    ) -> KnowledgeBaseResponse:
        """
        创建知识库

        流程：校验通过 → 确保模型配置存在 → 写库 → 提交
        """
        model = data.embedding_model or "bge-small-zh-v1.5"
        dim = data.embedding_dimension or 4096
        if data.cleaning_config is not None:
            cleaning_config = data.cleaning_config.model_dump(mode="json")
        else:
            cleaning_config = KnowledgeBaseService.get_default_cleaning_config()

        # 无用户配置 → 自动创建/查找本地默认配置，确保始终有关联
        config_id = data.user_model_config_id
        if not config_id:
            cfg = await _ensure_model_config(db, user.id, "local", model, dim)
            config_id = cfg.id

        kb = await KnowledgeBaseRepo.create(
            db,
            user_id=user.id,
            name=data.name,
            description=data.description,
            allowed_extensions=data.allowed_extensions,
            max_file_size=data.max_file_size or settings.storage.default_max_file_size,
            allow_multiple=data.allow_multiple,
            auto_process=(
                data.auto_process
                if data.auto_process is not None
                else KnowledgeBaseService.get_default_auto_process()
            ),
            chunk_size=(
                data.chunk_size
                if data.chunk_size is not None
                else getattr(settings.document, "default_chunk_size", 800)
            ),
            chunk_overlap=(
                data.chunk_overlap
                if data.chunk_overlap is not None
                else getattr(settings.document, "default_chunk_overlap", 150)
            ),
            chunk_separators=(
                data.chunk_separators
                if data.chunk_separators is not None
                else getattr(
                    settings.document,
                    "default_chunk_separators",
                    "\n##,\n###,\n,。,., ",
                )
            ),
            cleaning_config=cleaning_config,
            embedding_model=model,
            embedding_dimension=dim,
            user_model_config_id=config_id,
        )
        await db.commit()
        return KnowledgeBaseResponse.model_validate(kb)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user: Users,
        page: int = settings.pagination.default_page,
        page_size: int = settings.pagination.default_page_size,
    ) -> PaginatedResponse:
        """
        当前用户的知识库列表（分页）

        自动过滤 status=9（逻辑删除），按创建时间倒序
        """
        items, total = await KnowledgeBaseRepo.list_by_user(db, user.id, page, page_size)
        return PaginatedResponse(
            items=[KnowledgeBaseListItem.model_validate(kb) for kb in items],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    async def get(db: AsyncSession, user: Users, kb_id: UUID) -> KnowledgeBaseResponse:
        """
        获取单个知识库详情

        校验：存在性 → 归属 → 未删除
        """
        kb = await _get_kb_for_user(db, user, kb_id)
        return KnowledgeBaseResponse.model_validate(kb)

    @staticmethod
    async def update(
        db: AsyncSession,
        user: Users,
        kb_id: UUID,
        data: KnowledgeBaseUpdate,
    ) -> KnowledgeBaseResponse:
        """
        编辑知识库

        校验：归属 + 未删除
        仅更新传入的非 None 字段，未传的字段保持原值
        """
        kb = await _get_kb_for_user(db, user, kb_id)
        submitted_fields = set(data.model_dump(exclude_unset=True))
        strategy_fields = {
            "auto_process",
            "chunk_size",
            "chunk_overlap",
            "chunk_separators",
            "cleaning_config",
        }
        if submitted_fields & strategy_fields and await DocumentRepo.has_processing_in_kb(db, kb_id):
            raise HTTPException(status_code=409, detail="知识库有文件正在处理，暂不能修改处理策略")
        next_chunk_size = data.chunk_size if data.chunk_size is not None else kb.chunk_size
        next_chunk_overlap = (
            data.chunk_overlap if data.chunk_overlap is not None else kb.chunk_overlap
        )
        if next_chunk_overlap >= next_chunk_size:
            raise HTTPException(status_code=422, detail="chunk_overlap 必须小于 chunk_size")
        kb = await KnowledgeBaseRepo.update(
            db, kb,
            name=data.name,
            description=data.description,
            allowed_extensions=data.allowed_extensions,
            max_file_size=data.max_file_size,
            allow_multiple=data.allow_multiple,
            auto_process=data.auto_process,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
            chunk_separators=data.chunk_separators,
            cleaning_config=(
                data.cleaning_config.model_dump(mode="json")
                if data.cleaning_config is not None else None
            ),
            embedding_model=data.embedding_model,
            embedding_dimension=data.embedding_dimension,
            status=data.status,
        )
        # user_model_config_id 处理：显式设为 null → 自动创建本地默认配置
        set_fields = data.model_dump(exclude_unset=True)
        if 'user_model_config_id' in set_fields:
            config_id = data.user_model_config_id
            if not config_id:
                model = data.embedding_model or kb.embedding_model
                dim = data.embedding_dimension or kb.embedding_dimension
                cfg = await _ensure_model_config(db, user.id, "local", model, dim)
                config_id = cfg.id
            kb.user_model_config_id = config_id
        await db.commit()
        await db.refresh(kb)  # 重新加载 onupdate 触发的 updated_at，避免 MissingGreenlet
        return KnowledgeBaseResponse.model_validate(kb)

    @staticmethod
    async def delete(db: AsyncSession, user: Users, kb_id: UUID) -> None:
        """
        软删除知识库及其下所有文件（status → 9）
        """
        kb = await _get_kb_for_user(db, user, kb_id)
        await DocumentRepo.soft_delete_by_kb(db, kb_id)
        await DocumentRepo.soft_delete_chunks_by_kb(db, kb_id)  # 级联软删切片/向量
        await KnowledgeBaseRepo.soft_delete(db, kb)
        await db.commit()

    # ═══════════════════════════════════════════════
    # 文件管理
    # ═══════════════════════════════════════════════

    @staticmethod
    async def mark_processing(db: AsyncSession, doc_id: UUID) -> None:
        """
        标记文档为"处理中"（任务已入队，状态 2 落库）

        上传接口返回前调用：前端拉列表即可看到 解析/清洗/切片/向量化 均为"进行中"，
        避免后台任务尚未启动（BackgroundTasks 在响应后才执行）导致的"无反馈"空白期。
        任务正式启动时会重置状态走标准链路。
        """
        await KnowledgeBaseService.mark_processing_to_stage(db, doc_id, "vectorize")

    @staticmethod
    async def mark_processing_to_stage(
        db: AsyncSession,
        doc_id: UUID,
        target_stage: str,
    ) -> None:
        """按目标阶段预置处理中状态，避免未参与的后续阶段显示排队。"""
        stage_fields = {
            "parse": ("is_parsed",),
            "clean": ("is_parsed", "is_cleaned"),
            "chunk": ("is_parsed", "is_cleaned", "is_chunked"),
            "vectorize": ("is_parsed", "is_cleaned", "is_chunked", "is_vectorized"),
        }
        if target_stage not in stage_fields:
            raise ValueError(f"未知处理目标阶段: {target_stage}")
        doc = await DocumentRepo.get_by_id(db, doc_id)
        if doc is None or doc.status == 9:
            return
        for field in ("is_parsed", "is_cleaned", "is_chunked", "is_vectorized"):
            setattr(doc, field, 2 if field in stage_fields[target_stage] else 0)
        doc.last_error = None
        await db.commit()

    @staticmethod
    async def list_processing_tasks(
        db: AsyncSession,
        user: Users,
    ) -> list[dict]:
        """
        全局处理任务列表（处理浮窗轮询用）

        由文档四阶段状态推断阶段：
        - (2,2,2,2) → queued（入队标记，等待处理槽位）
        - is_parsed=2 → parsing；is_cleaned=2 → cleaning；is_chunked=2 → chunking；is_vectorized=2 → vectorizing
        """
        rows = await DocumentRepo.list_processing_tasks(db, user.id)
        for r in rows:
            if (r["is_parsed"] == 2 and r["is_cleaned"] == 2
                    and r["is_chunked"] == 2 and r["is_vectorized"] == 2):
                r["stage"] = "queued"
            elif r["is_parsed"] == 2:
                r["stage"] = "parsing"
            elif r["is_cleaned"] == 2:
                r["stage"] = "cleaning"
            elif r["is_chunked"] == 2:
                r["stage"] = "chunking"
            elif r["is_vectorized"] == 2:
                r["stage"] = "vectorizing"
            else:
                r["stage"] = "processing"
        return rows

    @staticmethod
    async def upload_file(
        db: AsyncSession,
        user: Users,
        kb_id: UUID,
        file: UploadFile,
    ) -> DocumentListItem:
        """
        上传文件到知识库

        流程：
        1. 校验知识库归属
        2. 校验文件扩展名（如果知识库配置了 allowed_extensions）
        3. 校验文件大小（不超过 max_file_size）
        4. 生成唯一文件名：{原名称}_{uuid8}.{ext}
        5. 写入磁盘：uploads/{kb_id}/{safe_name}
        6. 写入数据库文档记录
        """
        kb = await _get_kb_for_user(db, user, kb_id)

        # 扩展名校验
        if kb.allowed_extensions:
            allowed = [e.strip().lower() for e in kb.allowed_extensions.split(",") if e.strip()]
            ext = _Path(file.filename or "").suffix.lower()
            if allowed and ext not in allowed:
                raise HTTPException(status_code=400, detail=f"不支持的文件类型: {ext}")

        # 大小校验
        contents = await file.read()
        if len(contents) > kb.max_file_size:
            raise HTTPException(
                status_code=400,
                detail=f"文件大小超过限制 ({kb.max_file_size // 1024 // 1024}MB)",
            )

        # 生成存储路径
        original_name = file.filename or "unknown"
        stem = _Path(original_name).stem
        ext = _Path(original_name).suffix
        safe_name = f"{stem}_{str(_uuid.uuid4())[:8]}{ext}"
        kb_dir = UPLOAD_ROOT / str(kb_id)
        kb_dir.mkdir(parents=True, exist_ok=True)
        file_path = kb_dir / safe_name

        # 写磁盘
        file_path.write_bytes(contents)

        # 建记录（file_type 存后缀，无后缀则为 NULL）
        doc = await DocumentRepo.create(
            db,
            knowledge_base_id=kb_id,
            user_id=user.id,
            filename=original_name,
            file_path=str(file_path.relative_to(UPLOAD_ROOT)),
            file_size=len(contents),
            file_type=ext or None,
        )
        await db.commit()
        return DocumentListItem.model_validate(doc)

    @staticmethod
    async def list_files(
        db: AsyncSession,
        user: Users,
        kb_id: UUID,
        page: int = settings.pagination.default_page,
        page_size: int = settings.pagination.default_page_size,
    ) -> PaginatedResponse:
        """
        知识库文件列表（分页）

        校验：知识库归属 + 未删除
        自动过滤 status=9 的文件
        """
        kb = await _get_kb_for_user(db, user, kb_id)
        items, total = await DocumentRepo.list_by_kb(db, kb_id, page, page_size)
        chunk_counts = await DocumentRepo.count_active_chunks_by_documents(
            db, [doc.id for doc in items]
        )
        result_items: list[DocumentListItem] = []
        for doc in items:
            chunk_count = chunk_counts.get(doc.id, 0)
            result_items.append(_document_list_item(kb, doc, chunk_count))
        return PaginatedResponse(
            items=result_items,
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    async def update_document_strategy(
        db: AsyncSession,
        user: Users,
        kb_id: UUID,
        doc_id: UUID,
        data: DocumentProcessingStrategyUpdate,
    ) -> DocumentListItem:
        """保存文件独立策略或恢复继承；处理中时拒绝修改。"""
        kb = await _get_kb_for_user(db, user, kb_id)
        doc = await DocumentRepo.get_by_id(db, doc_id)
        if (
            doc is None
            or doc.status == 9
            or doc.knowledge_base_id != kb_id
            or doc.user_id != user.id
        ):
            raise HTTPException(status_code=404, detail="文件不存在")
        if await DocumentRepo.has_processing_in_kb(db, kb_id):
            raise HTTPException(status_code=409, detail="知识库有文件正在处理，暂不能修改处理策略")

        config = data.to_processing_config()
        doc.processing_config = (
            config.model_dump(mode="json") if config is not None else None
        )
        await db.commit()
        await db.refresh(doc)
        chunk_counts = await DocumentRepo.count_active_chunks_by_documents(db, [doc.id])
        return _document_list_item(kb, doc, chunk_counts.get(doc.id, 0))

    @staticmethod
    async def list_document_chunks(
        db: AsyncSession,
        user: Users,
        kb_id: UUID,
        doc_id: UUID,
        page: int,
        page_size: int,
    ) -> PaginatedResponse:
        """分页读取当前文件数据库中实际生效的切片。"""
        await _get_kb_for_user(db, user, kb_id)
        doc = await DocumentRepo.get_by_id(db, doc_id)
        if (
            doc is None
            or doc.status == 9
            or doc.knowledge_base_id != kb_id
            or doc.user_id != user.id
        ):
            raise HTTPException(status_code=404, detail="文件不存在")
        chunks, total = await DocumentRepo.list_active_chunks(
            db, kb_id, doc_id, page, page_size
        )
        return PaginatedResponse(
            items=[
                StoredChunkItem(
                    id=chunk.id,
                    index=chunk.chunk_index,
                    content=chunk.content,
                    char_count=len(chunk.content),
                    metadata=chunk.chunk_metadata,
                    is_vectorized=chunk.is_vectorized,
                )
                for chunk in chunks
            ],
            total=total,
            page=page,
            page_size=page_size,
        )

    @staticmethod
    async def delete_file(
        db: AsyncSession,
        user: Users,
        kb_id: UUID,
        doc_id: UUID,
    ) -> None:
        """
        软删除文件（status → 9）

        校验：
        1. 知识库归属当前用户
        2. 文档存在且属于该知识库
        3. 文档未被删除
        不删除磁盘文件（仅标记状态）
        """
        await _get_kb_for_user(db, user, kb_id)
        doc = await DocumentRepo.get_by_id(db, doc_id)
        if doc is None or doc.knowledge_base_id != kb_id:
            raise HTTPException(status_code=404, detail="文件不存在")
        if doc.status == 9:
            raise HTTPException(status_code=404, detail="文件已被删除")

        await DocumentRepo.soft_delete(db, doc)
        await DocumentRepo.soft_delete_chunks(db, [doc_id])  # 级联软删切片/向量
        await db.commit()

    # ═══════════════════════════════════════════════
    # 批量操作
    # ═══════════════════════════════════════════════

    @staticmethod
    async def batch_kb(
        db: AsyncSession,
        user: Users,
        ids: list[UUID],
        action: str,
    ) -> "BatchResult":
        """
        批量操作知识库：enable / disable / delete

        仅操作属于当前用户且未删除的知识库
        """
        from backend.schemas.knowledge import BatchResult

        if action == "delete":
            affected = await KnowledgeBaseRepo.batch_update_status(db, user.id, ids, 9)
        elif action == "enable":
            affected = await KnowledgeBaseRepo.batch_update_status(db, user.id, ids, 1)
        elif action == "disable":
            affected = await KnowledgeBaseRepo.batch_update_status(db, user.id, ids, 0)
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")

        await db.commit()
        failed_count = len(ids) - affected
        return BatchResult(
            success_count=affected,
            fail_count=failed_count,
        )

    @staticmethod
    async def batch_files(
        db: AsyncSession,
        user: Users,
        kb_id: UUID,
        ids: list[UUID],
        action: str,
    ) -> "BatchResult":
        """
        批量操作文件：delete

        先校验知识库归属，再批量删除文档
        """
        from backend.schemas.knowledge import BatchResult

        await _get_kb_for_user(db, user, kb_id)

        if action == "delete":
            affected = await DocumentRepo.batch_soft_delete(db, kb_id, user.id, ids)
            await DocumentRepo.soft_delete_chunks(db, ids)  # 级联软删切片/向量
        else:
            raise HTTPException(status_code=400, detail=f"不支持的操作: {action}")

        await db.commit()
        failed_count = len(ids) - affected
        return BatchResult(
            success_count=affected,
            fail_count=failed_count,
        )


# ── 内部工具 ──────────────────────────────

async def _get_kb_for_user(
    db: AsyncSession,
    user: Users,
    kb_id: UUID,
) -> KnowledgeBases:
    """
    查知识库 + 校验归属 + 校验未删除

    Raises:
        HTTPException 404: 不存在 / 已删除 / 不属于当前用户（统一报不存在，不泄露信息）
    """
    kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
    if kb is None or kb.status == 9:
        raise HTTPException(status_code=404, detail="知识库不存在")
    if kb.user_id != user.id:
        raise HTTPException(status_code=404, detail="知识库不存在")
    return kb
