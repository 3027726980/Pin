"""公开接口组：/api/v1/public/ —— 嵌入 widget 专用（API Key 鉴权，免登录）

设计：与主站接口隔离，复用 Service 层；访客身份 = JWT（登录）或 client_id（匿名）。
"""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.api.deps_public import get_optional_user, get_public_agent
from backend.core.database import get_db
from backend.core.utils import parse_page, parse_page_size
from backend.models import Users
from backend.schemas.agent import ChatRequest
from backend.schemas.auth import LoginRequest
from backend.schemas.common import SuccessResponse
from backend.schemas.conversation import ConversationResponse, MessageResponse
from backend.schemas.public import PublicChatRequest, PublicConversationCreate
from backend.services.auth import AuthService
from backend.services.chat import ChatService
from backend.services.conversation import ConversationService

router = APIRouter(prefix="/api/v1/public", tags=["公开接口"])


def _resolve_client_id(body_client_id: str | None, user: Users | None) -> str | None:
    """身份归一：登录态忽略 client_id；匿名必须提供 client_id"""
    if user is not None:
        return None
    if not body_client_id:
        raise HTTPException(status_code=422, detail="未登录时需提供 client_id")
    return body_client_id


@router.post("/auth/login", response_model=SuccessResponse,
             summary="访客登录（widget 内嵌表单用）")
async def public_login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录（与主站一致，token 存 widget 侧 localStorage）"""
    result = await AuthService.login(db, body.username, body.password)
    return SuccessResponse(result=result)


@router.post("/agents/{agent_id}/chat", response_model=SuccessResponse,
             summary="公开对话（流式/非流式）")
async def public_chat(
    agent_id: UUID,
    body: PublicChatRequest,
    db: AsyncSession = Depends(get_db),
    user: Users | None = Depends(get_optional_user),
    auth=Depends(get_public_agent("write")),
):
    """API Key 鉴权对话；登录态会话归 user，匿名会话归 client_id"""
    agent, owner = auth
    client_id = _resolve_client_id(body.client_id, user)
    chat_req = ChatRequest(
        message=body.message,
        conversation_id=body.conversation_id,
        stream=body.stream,
    )
    # 登录场景：会话归登录用户（user），agent/LLM 校验用所有者（exec_user）
    exec_user = owner if user else None
    actor = user if user else owner

    if not body.stream:
        result = await ChatService.chat(
            db, actor, agent_id, chat_req,
            client_id=client_id, exec_user=exec_user)
        return SuccessResponse(result=result)

    async def event_gen():
        try:
            async for event in ChatService.chat_stream(
                    db, actor, agent_id, chat_req,
                    client_id=client_id, exec_user=exec_user):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except HTTPException as e:
            yield f"data: {json.dumps({'type': 'error', 'code': e.status_code, 'message': e.detail}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")


@router.post("/conversations", response_model=SuccessResponse[ConversationResponse],
             summary="公开创建会话")
async def public_create_conversation(
    body: PublicConversationCreate,
    db: AsyncSession = Depends(get_db),
    user: Users | None = Depends(get_optional_user),
    auth=Depends(get_public_agent("write")),
):
    """创建会话（登录态归 user，匿名归 client_id）"""
    agent, owner = auth
    client_id = _resolve_client_id(body.client_id, user)
    exec_user = owner if user else None
    result = await ConversationService.create(
        db, user if user else owner, body.agent_id,
        client_id=client_id, exec_user=exec_user)
    return SuccessResponse(result=result)


@router.get("/conversations", response_model=SuccessResponse,
            summary="公开会话列表")
async def public_list_conversations(
    agent_id: UUID = Query(..., description="Agent ID"),
    client_id: str | None = Query(None, description="匿名访客标识"),
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    db: AsyncSession = Depends(get_db),
    user: Users | None = Depends(get_optional_user),
    auth=Depends(get_public_agent("read")),
):
    """会话列表：登录态按 user 查，匿名按 client_id 查（惰性清理超期匿名会话）"""
    agent, owner = auth
    p, ps = parse_page(page), parse_page_size(page_size)
    if user is not None:
        items, total = await ConversationService.list_by_user(
            db, user, agent_id, p, ps)
    else:
        if not client_id:
            raise HTTPException(status_code=422, detail="未登录时需提供 client_id")
        items, total = await ConversationService.list_by_client(
            db, agent, client_id, p, ps)
    return SuccessResponse(result={
        "items": items, "total": total, "page": p, "page_size": ps})


@router.delete("/conversations/{conv_id}", response_model=SuccessResponse,
              summary="公开删除会话")
async def public_delete_conversation(
    conv_id: UUID,
    client_id: str | None = Query(None, description="匿名访客标识"),
    db: AsyncSession = Depends(get_db),
    user: Users | None = Depends(get_optional_user),
    auth=Depends(get_public_agent("write")),
):
    """删除会话（登录态按 user 归属，匿名按 client_id；写操作走限流）"""
    agent, owner = auth
    resolved = _resolve_client_id(client_id, user)
    await ConversationService.delete(
        db, user if user else owner, conv_id, client_id=resolved)
    return SuccessResponse(result=None)


@router.get("/conversations/{conv_id}/messages", response_model=SuccessResponse,
            summary="公开历史消息")
async def public_list_messages(
    conv_id: UUID,
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    client_id: str | None = Query(None, description="匿名访客标识"),
    db: AsyncSession = Depends(get_db),
    user: Users | None = Depends(get_optional_user),
    auth=Depends(get_public_agent("read")),
):
    """历史消息（校验归属：user 或 client_id）"""
    agent, owner = auth
    p, ps = parse_page(page), parse_page_size(page_size)
    msgs, total = await ConversationService.get_messages(
        db, user, conv_id, p, ps,
        client_id=None if user else client_id)
    return SuccessResponse(result={
        "items": [MessageResponse.model_validate(m) for m in msgs],
        "total": total, "page": p, "page_size": ps})
