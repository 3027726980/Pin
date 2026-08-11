"""Agent 嵌入密钥路由（主站登录态）"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.models import Users
from backend.schemas.agent_api_key import (
    AgentApiKeyCreate,
    AgentApiKeyResponse,
    AgentApiKeyUpdate,
)
from backend.schemas.common import SuccessResponse
from backend.services.agent_api_key import AgentApiKeyService

router = APIRouter(prefix="/api/v1/agents", tags=["Agent 嵌入密钥"])


@router.get("/{agent_id}/api-keys", response_model=SuccessResponse,
            summary="密钥列表")
async def list_api_keys(
    agent_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """Agent 嵌入密钥列表（不含明文）"""
    keys = await AgentApiKeyService.list_by_agent(db, user, agent_id)
    return SuccessResponse(result=keys)


@router.post("/{agent_id}/api-keys", response_model=SuccessResponse,
             summary="生成密钥（明文只返回一次）")
async def create_api_key(
    agent_id: UUID,
    body: AgentApiKeyCreate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """生成嵌入密钥；明文仅本次返回，服务端只存哈希"""
    key = await AgentApiKeyService.create(db, user, agent_id, body.name)
    return SuccessResponse(result=key)


@router.put("/{agent_id}/api-keys/{key_id}", response_model=SuccessResponse,
            summary="编辑密钥（备注/启停）")
async def update_api_key(
    agent_id: UUID,
    key_id: UUID,
    body: AgentApiKeyUpdate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    key = await AgentApiKeyService.update(
        db, user, agent_id, key_id, body.name, body.enabled)
    return SuccessResponse(result=key)


@router.delete("/{agent_id}/api-keys/{key_id}", response_model=SuccessResponse,
               summary="吊销密钥")
async def delete_api_key(
    agent_id: UUID,
    key_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """吊销密钥（立即失效，所有使用该 Key 的嵌入页面停止工作）"""
    await AgentApiKeyService.delete(db, user, agent_id, key_id)
    return SuccessResponse(result=None)
