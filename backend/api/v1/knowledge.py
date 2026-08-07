"""
知识库 + 文件管理 路由

分页参数使用 str 类型接收，避免 FastAPI 对空字符串做 int 解析报错。
"""
from uuid import UUID

from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.config import settings
from backend.core.database import get_db
from backend.models import User
from backend.schemas.common import SuccessResponse
from backend.schemas.knowledge import (
    BatchFileAction,
    BatchKnowledgeBaseAction,
    BatchResult,
    ChunkIdsRequest,
    DocIdsRequest,
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    PaginatedResponse,
    ProcessResult,
)
from backend.services import KnowledgeBaseService
from backend.services.document_process_service import DocumentProcessService
from backend.services.knowledge_service import _get_kb_for_user

router = APIRouter(prefix="/api/v1/knowledge-bases", tags=["知识库"])


# ── 工具函数 ────────────────────────────

def _parse_page(raw: str) -> int:
    """安全解析分页参数：空/非数字 → py出默认值"""
    val = raw.strip() if raw else ""
    if not val:
        return settings.pagination.default_page
    try:
        n = int(val)
        return n if n > 0 else settings.pagination.default_page
    except ValueError:
        return settings.pagination.default_page


def _parse_page_size(raw: str) -> int:
    """安全解析每页条数：空/非数字 → py出默认值，上限受 max_page_size 约束"""
    val = raw.strip() if raw else ""
    if not val:
        return settings.pagination.default_page_size
    try:
        n = int(val)
        n = n if n > 0 else settings.pagination.default_page_size
        return min(n, settings.pagination.max_page_size)
    except ValueError:
        return settings.pagination.default_page_size


# ── 知识库 CRUD ────────────────────────

@router.get("", response_model=SuccessResponse[PaginatedResponse], summary="知识库列表")
async def list_kb(
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.list_by_user(
        db, user, _parse_page(page), _parse_page_size(page_size)
    )
    return SuccessResponse(result=result)


@router.post("", response_model=SuccessResponse[KnowledgeBaseResponse], summary="创建知识库")
async def create_kb(
    body: KnowledgeBaseCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.create(db, user, body)
    return SuccessResponse(result=result)


@router.get("/{kb_id}", response_model=SuccessResponse[KnowledgeBaseResponse], summary="知识库详情")
async def get_kb(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.get(db, user, kb_id)
    return SuccessResponse(result=result)


@router.put("/{kb_id}", response_model=SuccessResponse[KnowledgeBaseResponse], summary="编辑知识库")
async def update_kb(
    kb_id: UUID,
    body: KnowledgeBaseUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.update(db, user, kb_id, body)
    return SuccessResponse(result=result)


@router.delete("/{kb_id}", response_model=SuccessResponse, summary="删除知识库")
async def delete_kb(
    kb_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await KnowledgeBaseService.delete(db, user, kb_id)
    return SuccessResponse(message="已删除")


# ── 文档处理 ────────────────────────────

@router.post("/{kb_id}/parse", response_model=SuccessResponse[ProcessResult], summary="触发文档解析")
async def parse_docs(
    kb_id: UUID,
    body: DocIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    processed = await DocumentProcessService.parse_documents(db, kb, body.doc_ids)
    await db.commit()
    return SuccessResponse(result=ProcessResult(processed=processed, total=len(body.doc_ids)))


@router.post("/{kb_id}/chunk", response_model=SuccessResponse[ProcessResult], summary="触发文档分块")
async def chunk_docs(
    kb_id: UUID,
    body: DocIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    processed = await DocumentProcessService.chunk_documents(db, kb, body.doc_ids)
    await db.commit()
    return SuccessResponse(result=ProcessResult(processed=processed, total=len(body.doc_ids)))


@router.post("/{kb_id}/vectorize", response_model=SuccessResponse[ProcessResult], summary="触发向量化")
async def vectorize_chunks(
    kb_id: UUID,
    body: ChunkIdsRequest,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    kb = await _get_kb_for_user(db, user, kb_id)
    processed = await DocumentProcessService.vectorize_chunks(db, kb, body.chunk_ids)
    await db.commit()
    return SuccessResponse(result=ProcessResult(processed=processed, total=len(body.chunk_ids)))


# ── 批量操作 ────────────────────────────

@router.post("/batch", response_model=SuccessResponse[BatchResult], summary="批量操作知识库")
async def batch_kb(
    body: BatchKnowledgeBaseAction,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.batch_kb(db, user, body.ids, body.action)
    return SuccessResponse(result=result)


# ── 文件管理 ────────────────────────────

@router.post(
    "/{kb_id}/files",
    response_model=SuccessResponse,
    summary="上传文件",
)
async def upload_file(
    kb_id: UUID,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.upload_file(db, user, kb_id, file)
    return SuccessResponse(result=result)


@router.get(
    "/{kb_id}/files",
    response_model=SuccessResponse[PaginatedResponse],
    summary="文件列表",
)
async def list_files(
    kb_id: UUID,
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.list_files(
        db, user, kb_id, _parse_page(page), _parse_page_size(page_size)
    )
    return SuccessResponse(result=result)


@router.delete(
    "/{kb_id}/files/{doc_id}",
    response_model=SuccessResponse,
    summary="删除文件",
)
async def delete_file(
    kb_id: UUID,
    doc_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await KnowledgeBaseService.delete_file(db, user, kb_id, doc_id)
    return SuccessResponse(message="已删除")


@router.post(
    "/{kb_id}/files/batch",
    response_model=SuccessResponse[BatchResult],
    summary="批量操作文件",
)
async def batch_files(
    kb_id: UUID,
    body: BatchFileAction,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await KnowledgeBaseService.batch_files(db, user, kb_id, body.ids, body.action)
    return SuccessResponse(result=result)
