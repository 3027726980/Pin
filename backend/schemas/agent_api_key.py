"""Agent 嵌入密钥请求/响应 Schema"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class AgentApiKeyCreate(BaseModel):
    """生成密钥"""
    name: str | None = Field(None, max_length=100, description="备注")


class AgentApiKeyUpdate(BaseModel):
    """编辑密钥（备注/启停）"""
    name: str | None = Field(None, max_length=100, description="备注")
    enabled: int | None = Field(None, ge=0, le=1, description="1=启用 0=禁用")


class AgentApiKeyResponse(BaseModel):
    """密钥信息（不含明文）"""
    id: UUID
    agent_id: UUID
    name: str | None
    enabled: int
    last_used_at: datetime | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentApiKeyCreated(AgentApiKeyResponse):
    """生成结果（明文仅此一次返回）"""
    api_key: str = Field(..., description="明文密钥，仅生成时返回一次")
