# 作者：LHF；时间：2026-10-25；作用：支持上下文比例压缩、手动压缩或模型输入日志。
"""公开接口组：/api/v1/public/ —— 嵌入 widget 专用（API Key 鉴权，免登录）

设计：与主站接口隔离，复用 Service 层；访客身份 = JWT（登录）或 client_id（匿名）。
"""
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

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
from backend.services.turn_stream import (
    encode_sse,
    filter_event_visibility,
)

router = APIRouter(prefix="/api/v1/public", tags=["公开接口"])


@router.get("/agents/{agent_id}/capabilities")
async def public_capabilities(agent_id: UUID, db=Depends(get_db), auth=Depends(get_public_agent("read"))):
    """作者：LHF；2026-10-25；公开端仅发现 Key 绑定 Agent 的有效技能与业务工具。"""
    from backend.skills.service import agent_capabilities

    _, owner = auth
    return SuccessResponse(result=await agent_capabilities(db, owner, agent_id))


@router.get("/agents/{agent_id}/skill-runs/{run_id}/artifacts")
async def public_artifact(agent_id: UUID, run_id: str, path: str = Query(...),
                          client_id: str | None = Query(None), db=Depends(get_db),
                          user=Depends(get_optional_user), auth=Depends(get_public_agent("read"))):
    """作者：LHF；2026-10-25；按 Key、Agent 及访客/登录会话归属下载脚本产物。"""
    from fastapi import HTTPException
    from backend.repositories import ConversationRepo
    from backend.skills import SkillRegistry
    from backend.skills.runtime import artifact_file

    _, owner = auth
    target, conversation_id = artifact_file(SkillRegistry(), owner.id, agent_id, run_id, path)
    conv = await ConversationRepo.get_by_id(db, UUID(conversation_id))
    anonymous = _resolve_client_id(client_id, user)
    if (conv is None or conv.status == 9 or conv.agent_id != agent_id
            or (user is not None and conv.user_id != user.id)
            or (user is None and (conv.user_id is not None or conv.client_id != anonymous))):
        raise HTTPException(404, "产物不存在")
    return FileResponse(target, filename=target.name, media_type="application/octet-stream")


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
    request: Request,
    db: AsyncSession = Depends(get_db),
    user: Users | None = Depends(get_optional_user),
    auth=Depends(get_public_agent("write")),
):
    """API Key 鉴权对话；登录态会话归 user，匿名会话归 client_id"""
    agent, owner = auth
    client_id = _resolve_client_id(body.client_id, user)
    chat_req = ChatRequest(
        message=body.message,
        mentions=body.mentions,
        conversation_id=body.conversation_id,
        stream=body.stream,
    )
    # 登录场景：会话归登录用户（user），agent/LLM 校验用所有者（exec_user）
    exec_user = owner if user else None
    actor = user if user else owner

    if not body.stream:
        result = await ChatService.chat(
            db, actor, agent_id, chat_req,
            client_id=client_id, exec_user=exec_user, include_debug=False)
        return SuccessResponse(result=result)

    async def event_gen():
        async for event in ChatService.chat_stream(
                db, actor, agent_id, chat_req,
                client_id=client_id, exec_user=exec_user,
                request_id=request.scope.get("state", {}).get("request_id")):
            visible = filter_event_visibility(event, public=True)
            if visible is not None:
                yield encode_sse(visible)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


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


@router.post("/conversations/{conv_id}/compact", response_model=SuccessResponse,
             summary="公开手动压缩会话上下文")
async def public_compact_conversation(
    conv_id: UUID,
    agent_id: UUID,
    client_id: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
    user: Users | None = Depends(get_optional_user),
    auth=Depends(get_public_agent("write")),
):
    """作者：LHF；2026-10-25；校验 Key、Agent 和访客归属后压缩记忆。"""
    agent, owner = auth
    resolved = _resolve_client_id(client_id, user)
    result = await ConversationService.compact(
        db, user if user else owner, conv_id, client_id=resolved,
        exec_user=owner if user else None, agent_id=agent.id)
    # 公开端不暴露管理端 Trace 标识或详细容量配置。
    return SuccessResponse(result={key: result[key] for key in (
        "compressed", "before_tokens", "after_tokens")})


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
