"""会话路由:创建/列表/历史消息/删除"""
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

router = APIRouter(prefix="/api/v1/conversations", tags=["会话"])


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
