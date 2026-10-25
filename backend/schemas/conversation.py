# 作者：LHF；时间：2026-10-25；作用：定义会话历史及持久化 Trace 关联响应。
"""会话请求/响应 Schema"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field
from backend.skills.schemas import CapabilityMention, SkillArtifact


class ConversationCreate(BaseModel):
    """创建会话"""
    agent_id: UUID = Field(..., description="归属 Agent ID")


class ConversationResponse(BaseModel):
    """会话详情"""
    id: UUID
    agent_id: UUID
    title: str | None
    message_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class MessageResponse(BaseModel):
    """会话消息（无 id：消息存于会话 JSON 数组，前端以索引/本地 uid 定位）"""
    role: str
    content: str
    mentions: list[CapabilityMention] = Field(default_factory=list)
    artifacts: list[SkillArtifact] = Field(default_factory=list)
    citations: list | None = None
    citation_bindings: list | None = None
    trace_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}
