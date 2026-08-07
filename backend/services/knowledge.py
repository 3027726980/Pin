"""
知识库 + 文档 业务逻辑

- 知识库 CRUD：创建 → 列表 → 详情 → 编辑 → 软删除
- 文件管理：上传校验（类型/大小）→ 写磁盘 → 入库 → 软删除
- 所有操作均校验：知识库归属当前用户 + 状态非删除
"""
import uuid as _uuid

from pathlib import Path as _Path
from uuid import UUID

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import PROJECT_ROOT, settings
from backend.models import KnowledgeBases, Users
from backend.repositories import DocumentRepo, KnowledgeBaseRepo
from backend.schemas.knowledge import (
    DocumentListItem,
    KnowledgeBaseCreate,
    KnowledgeBaseListItem,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    PaginatedResponse,
)

# 上传根目录（从 config.yaml 读取，相对于项目根）
UPLOAD_ROOT = PROJECT_ROOT / settings.storage.upload_dir


class KnowledgeBaseService:
    """知识库 + 文件 业务逻辑 —— 不依赖 HTTP 请求/响应，只处理数据和规则"""

    # ═══════════════════════════════════════════════
    # 知识库 CRUD
    # ═══════════════════════════════════════════════

    @staticmethod
    async def create(
        db: AsyncSession,
        user: Users,
        data: KnowledgeBaseCreate,
    ) -> KnowledgeBaseResponse:
        """
        创建知识库

        流程：校验通过 → 写库 → 提交 → 返回响应
        无额外校验（创建不需要检查重名等）
        """
        kb = await KnowledgeBaseRepo.create(
            db,
            user_id=user.id,
            name=data.name,
            description=data.description,
            allowed_extensions=data.allowed_extensions,
            max_file_size=data.max_file_size or settings.storage.default_max_file_size,
            allow_multiple=data.allow_multiple,
            chunk_size=data.chunk_size or 800,
            chunk_overlap=data.chunk_overlap or 150,
            chunk_separators=data.chunk_separators or "\n##,\n###,\n,。,., ",
            embedding_model=data.embedding_model or "bge-small-zh-v1.5",
            embedding_dimension=data.embedding_dimension or 4096,
            user_model_config_id=data.user_model_config_id,
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
        kb = await KnowledgeBaseRepo.update(
            db, kb,
            name=data.name,
            description=data.description,
            allowed_extensions=data.allowed_extensions,
            max_file_size=data.max_file_size,
            allow_multiple=data.allow_multiple,
            chunk_size=data.chunk_size,
            chunk_overlap=data.chunk_overlap,
            chunk_separators=data.chunk_separators,
            embedding_model=data.embedding_model,
            embedding_dimension=data.embedding_dimension,
            status=data.status,
        )
        # user_model_config_id 需显式处理：允许设为 None 以切换回本地模型
        set_fields = data.model_dump(exclude_unset=True)
        if 'user_model_config_id' in set_fields:
            kb.user_model_config_id = data.user_model_config_id
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
        await KnowledgeBaseRepo.soft_delete(db, kb)
        await db.commit()

    # ═══════════════════════════════════════════════
    # 文件管理
    # ═══════════════════════════════════════════════

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
        await _get_kb_for_user(db, user, kb_id)
        items, total = await DocumentRepo.list_by_kb(db, kb_id, page, page_size)
        return PaginatedResponse(
            items=[DocumentListItem.model_validate(doc) for doc in items],
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
