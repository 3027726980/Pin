"""公开接口（/api/v1/public）请求/响应 Schema

匿名场景：client_id 标识访客；登录场景：JWT 优先，client_id 忽略。
"""
from uuid import UUID

from pydantic import BaseModel, Field

from backend.schemas.agent import ChatRequest


class PublicChatRequest(ChatRequest):
    """公开对话请求：在 ChatRequest 基础上增加匿名访客标识"""
    client_id: str | None = Field(
        None, min_length=8, max_length=64,
        description="匿名访客标识（未登录时必传，登录后忽略）")


class PublicConversationCreate(BaseModel):
    """公开创建会话"""
    agent_id: UUID = Field(..., description="归属 Agent ID")
    client_id: str | None = Field(
        None, min_length=8, max_length=64,
        description="匿名访客标识（未登录时必传，登录后忽略）")
