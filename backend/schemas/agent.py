"""
Agent 请求/响应 Schema

- AgentCreate / AgentUpdate：创建/编辑请求
- AgentResponse：详情 + 创建/编辑 响应（含 kb 名称、LLM 配置摘要）
- AgentListItem：列表响应（精简，仅表格需要）
- ChatRequest / ChatResponse / Citation：RAG 对话
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


# ── Agent CRUD ──────────────────────────

class AgentCreate(BaseModel):
    """创建 Agent"""
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    kb_id: UUID = Field(..., description="绑定的知识库 ID")
    llm_config_id: UUID = Field(..., description="LLM 模型配置 ID（model_type=2）")
    system_prompt: str | None = Field(None, description="系统提示词，不传则使用默认 RAG 模板")
    top_k: int = Field(5, ge=1, le=50)
    score_threshold: float = Field(0.3, ge=0.0, le=1.0)
    temperature: float = Field(0.7, ge=0.0, le=2.0)
    top_p: float = Field(0.9, ge=0.0, le=1.0)
    welcome_message: str | None = Field(None, max_length=500)


class AgentUpdate(BaseModel):
    """编辑 Agent（全部可选）"""
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    kb_id: UUID | None = None
    llm_config_id: UUID | None = None
    system_prompt: str | None = None
    top_k: int | None = Field(None, ge=1, le=50)
    score_threshold: float | None = Field(None, ge=0.0, le=1.0)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    top_p: float | None = Field(None, ge=0.0, le=1.0)
    welcome_message: str | None = Field(None, max_length=500)
    status: int | None = Field(None, ge=0, le=9)


class AgentResponse(BaseModel):
    """Agent 详情/创建/编辑 响应"""
    id: UUID
    name: str
    description: str | None
    kb_id: UUID
    kb_name: str | None = None
    llm_config_id: UUID
    llm_provider: str | None = None
    llm_model: str | None = None
    system_prompt: str
    top_k: int
    score_threshold: float
    temperature: float
    top_p: float
    welcome_message: str | None
    status: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentListItem(BaseModel):
    """Agent 列表项（仅表格需要）"""
    id: UUID
    name: str
    description: str | None
    kb_id: UUID
    kb_name: str | None = None
    llm_model: str | None = None
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BatchAgentAction(BaseModel):
    """批量操作 Agent"""
    ids: list[UUID] = Field(..., min_length=1, max_length=100)
    action: Literal["enable", "disable", "delete"]


# ── RAG 对话 ────────────────────────────

class ChatMessage(BaseModel):
    """对话历史消息"""
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    """对话请求"""
    message: str = Field(..., min_length=1, max_length=4000)
    history: list[ChatMessage] = Field(default_factory=list, max_length=10, description="最近对话历史，最多 10 条")
    stream: bool = Field(False, description="true=SSE 流式返回")


class Citation(BaseModel):
    """引用来源"""
    chunk_id: UUID
    document_name: str
    content: str
    score: float


class ChatResponse(BaseModel):
    """非流式对话响应"""
    answer: str
    citations: list[Citation] = []
