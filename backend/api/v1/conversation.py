# 作者：LHF；时间：2026-10-25；作用：支持上下文比例压缩、手动压缩或模型输入日志。
"""会话路由:创建/列表/历史消息/删除"""
import asyncio
from uuid import UUID

from fastapi import APIRouter, Depends, Query

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.core.utils import parse_page, parse_page_size
from backend.models import Users
from backend.schemas.common import SuccessResponse
from backend.schemas.conversation import (
    ConversationCreate,
    ConversationResponse,
    MessageResponse,
)
from backend.schemas.knowledge import PaginatedResponse
from backend.services.conversation import ConversationService
from backend.skills.schemas import ContextPreviewRequest

router = APIRouter(prefix="/api/v1/conversations", tags=["会话"])


@router.post("/{conv_id}/context-preview", summary="只读估算草稿和技能上下文")
async def context_preview(conv_id: UUID, body: ContextPreviewRequest, db=Depends(get_db), user=Depends(get_current_user)):
    """作者：LHF；2026-10-25；预览不执行工具、不迁移或写入 checkpoint。"""
    return SuccessResponse(result=await ConversationService.context_usage(db, user, conv_id, body))


@router.get("/{conv_id}/context-usage", summary="查询会话上下文容量估算")
async def get_context_usage(
    conv_id: UUID,
    db=Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """作者：LHF；2026-10-25；返回管理端所属会话的上下文估算和模型输入容量。"""
    return SuccessResponse(result=await ConversationService.context_usage(db, user, conv_id))


@router.post("/{conv_id}/compact", summary="手动压缩会话上下文")
async def compact_conversation(
    conv_id: UUID,
    db=Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """作者：LHF；2026-10-25；压缩当前用户的会话记忆并返回前后统计及 Trace。"""
    result = await ConversationService.compact(db, user, conv_id)
    return SuccessResponse(result=result)


@router.post("", response_model=SuccessResponse[ConversationResponse],
             summary="创建会话")
async def create_conversation(
    body: ConversationCreate,
    db=Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """创建会话(自动生成标题,id 即 checkpoint thread_id)"""
    result = await ConversationService.create(db, user, body.agent_id)
    return SuccessResponse(result=result)


@router.get("", response_model=SuccessResponse[PaginatedResponse],
            summary="会话列表")
async def list_conversations(
    agent_id: UUID | None = Query(None, description="按 Agent 过滤"),
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    db=Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """当前用户的会话列表(分页,含消息数)"""
    items, total = await ConversationService.list_by_user(
        db, user, agent_id, parse_page(page), parse_page_size(page_size))
    return SuccessResponse(result=PaginatedResponse(
        items=items, total=total, page=parse_page(page),
        page_size=parse_page_size(page_size)))


@router.get("/{conv_id}/messages", summary="历史消息")
async def list_messages(
    conv_id: UUID,
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    db=Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """会话历史消息(分页,含 citations)"""
    msgs, total = await ConversationService.get_messages(
        db, user, conv_id, parse_page(page), parse_page_size(page_size))
    # 作者：LHF；2026-10-25；旧消息仅在管理端按现存日志唯一恢复，扫描在线程执行，不影响公开接口。
    if user.is_superuser:
        from backend.services.trace_query import trace_query_service

        msgs = await asyncio.to_thread(trace_query_service.restore_message_trace_ids, conv_id, msgs)
    return SuccessResponse(result=PaginatedResponse(
        items=[MessageResponse.model_validate(m) for m in msgs],
        total=total, page=parse_page(page), page_size=parse_page_size(page_size)))


@router.delete("/{conv_id}", summary="删除会话")
async def delete_conversation(
    conv_id: UUID,
    db=Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """删除会话(软删 + 清理 checkpoint)"""
    await ConversationService.delete(db, user, conv_id)
    return SuccessResponse(message="已删除")
