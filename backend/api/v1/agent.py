"""
Agent 路由

- CRUD + 批量操作（照抄 knowledge 模式）
- POST /{agent_id}/chat：RAG 对话，stream 参数切换流式/非流式
"""
import json
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.core.utils import parse_page, parse_page_size
from backend.models import Users
from backend.schemas.agent import (
    AgentCreate,
    AgentResponse,
    AgentUpdate,
    BatchAgentAction,
    ChatRequest,
)
from backend.schemas.common import SuccessResponse
from backend.schemas.knowledge import BatchResult, PaginatedResponse
from backend.services import AgentService
from backend.services.chat import ChatService

router = APIRouter(prefix="/api/v1/agents", tags=["Agent"])


# ── CRUD ────────────────────────────────

@router.get("", response_model=SuccessResponse[PaginatedResponse], summary="获取当前用户的 Agent 列表", description="自动过滤已删除(status=9)的记录，按创建时间倒序；type 可选：simple_rag / general")
async def list_agents(
    page: str = Query("", description="页码，默认 1"),
    page_size: str = Query("", description="每页条数，默认 20"),
    type: str | None = Query(None, description="Agent 类型筛选：simple_rag / general"),
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await AgentService.list_by_user(
        db, user, parse_page(page), parse_page_size(page_size), type
    )
    return SuccessResponse(result=result)


@router.post("", response_model=SuccessResponse[AgentResponse], summary="创建新 Agent", description="type=simple_rag（知识库直接绑定）或 general（工具注册）；校验 LLM 配置与知识库归属")
async def create_agent(
    body: AgentCreate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await AgentService.create(db, user, body)
    return SuccessResponse(result=result)


@router.get("/{agent_id}", response_model=SuccessResponse[AgentResponse], summary="获取指定 Agent 的详细信息", description="包含绑定的知识库名称、LLM 配置摘要")
async def get_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await AgentService.get(db, user, agent_id)
    return SuccessResponse(result=result)


@router.put("/{agent_id}", response_model=SuccessResponse[AgentResponse], summary="修改 Agent 配置", description="可修改名称/描述/绑定/提示词/参数等，仅更新传入的非空字段")
async def update_agent(
    agent_id: UUID,
    body: AgentUpdate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await AgentService.update(db, user, agent_id, body)
    return SuccessResponse(result=result)


@router.delete("/{agent_id}", response_model=SuccessResponse, summary="删除 Agent", description="软删除，仅标记状态不删除数据")
async def delete_agent(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    await AgentService.delete(db, user, agent_id)
    return SuccessResponse(message="已删除")


# ── 批量操作 ────────────────────────────

@router.post("/batch", response_model=SuccessResponse[BatchResult], summary="批量操作 Agent", description="支持批量启用、禁用、删除，仅操作当前用户的 Agent")
async def batch_agents(
    body: BatchAgentAction,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await AgentService.batch(db, user, body.ids, body.action)
    return SuccessResponse(result=result)


# ── RAG 对话 ────────────────────────────

@router.post("/{agent_id}/chat", summary="与 Agent 对话", description="按 Agent 类型分发：simple_rag 固定检索知识库回答；general 由 LLM 自主决策调用工具（可多轮）；stream=true 时返回 SSE 流式事件（delta/citations/done）")
async def chat_agent(
    agent_id: UUID,
    body: ChatRequest,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    if not body.stream:
        result = await ChatService.chat(db, user, agent_id, body)
        return SuccessResponse(result=result)

    async def event_gen():
        try:
            async for event in ChatService.chat_stream(db, user, agent_id, body):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except HTTPException as e:
            # 校验类错误（如 Agent 不存在）在 SSE 中作为 error 事件返回
            yield f"data: {json.dumps({'type': 'error', 'code': e.status_code, 'message': e.detail}, ensure_ascii=False)}\n\n"
            yield "data: {\"type\": \"done\"}\n\n"

    return StreamingResponse(event_gen(), media_type="text/event-stream")
