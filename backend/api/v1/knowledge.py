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
    KnowledgeBaseCreate,
    KnowledgeBaseResponse,
    KnowledgeBaseUpdate,
    PaginatedResponse,
)
from backend.services import KnowledgeBaseService

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
