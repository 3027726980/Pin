"""
Agent 请求/响应 Schema

Agent 分类（type 字段区分，不同表存储）：
  - simple_rag：简单 RAG Agent，仅 RAG 功能，知识库直接绑定（kb_id/top_k/score_threshold 为表字段）
  - general：综合 Agent，能力以工具列表注册（tools JSONB）
  - workflow：MVP 不做，后续新增

请求：AgentCreate 为 discriminated union（按 type 精确校验各类型必填字段）
响应：统一结构（type + 各类型字段可空），前端按 type 渲染
"""
from datetime import datetime
from typing import Annotated, Literal, Union
from uuid import UUID

from pydantic import BaseModel, Field


# ── 工具配置（general Agent 用）─────────

class ToolConfig(BaseModel):
    """工具配置：MVP 仅 rag（知识库检索），扩展新工具时扩充 type 并加字段"""
    type: Literal["rag"]
    kb_id: UUID = Field(..., description="rag 工具绑定的知识库 ID")
    top_k: int | None = Field(None, ge=1, le=50, description="检索返回块数，不传用 config.yaml tools.default_top_k")
    score_threshold: float | None = Field(None, ge=0.0, le=1.0, description="相似度阈值，不传用 config.yaml tools.default_score_threshold")
    # ── Phase 4.6 检索增强（可空，空 → config.yaml 默认）──
    mqe_enabled: bool | None = Field(None, description="多查询扩展（MQE），不传用 config.yaml tools.default_mqe_enabled")
    hyde_enabled: bool | None = Field(None, description="假设文档嵌入（HyDE），不传用 config.yaml tools.default_hyde_enabled")
    mqe_query_count: int | None = Field(None, ge=2, le=5, description="MQE 改写子问题数，不传用 config.yaml tools.default_mqe_query_count")
    rerank_enabled: bool | None = Field(None, description="Rerank 精排开关，不传用 config.yaml tools.default_rerank_enabled")
    kb_name: str | None = Field(None, description="响应补全：知识库名称（请求时忽略）")


# ── 创建请求（discriminated union）──────

class SimpleRagAgentCreate(BaseModel):
    """简单 RAG Agent：仅 RAG 功能，知识库直接绑定"""
    type: Literal["simple_rag"] = "simple_rag"
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    kb_id: UUID = Field(..., description="绑定的知识库 ID")
    llm_config_id: UUID = Field(..., description="LLM 模型配置 ID（model_type=2）")
    summary_llm_config_id: UUID | None = Field(
        None, description="总结模型配置 ID（model_type=2）；空 = 跟随对话模型")
    top_k: int | None = Field(None, ge=1, le=50, description="检索返回块数，不传用 config.yaml tools.default_top_k")
    score_threshold: float | None = Field(None, ge=0.0, le=1.0, description="相似度阈值，不传用 config.yaml tools.default_score_threshold")
    # ── Phase 4.6 检索增强 ──
    mqe_enabled: bool | None = Field(None, description="多查询扩展（MQE），不传用 config.yaml tools.default_mqe_enabled")
    hyde_enabled: bool | None = Field(None, description="假设文档嵌入（HyDE），不传用 config.yaml tools.default_hyde_enabled")
    mqe_query_count: int | None = Field(None, ge=2, le=5, description="MQE 改写子问题数，不传用 config.yaml tools.default_mqe_query_count")
    rerank_enabled: bool | None = Field(None, description="Rerank 精排开关，不传用 config.yaml tools.default_rerank_enabled")
    enhance_llm_config_id: UUID | None = Field(
        None, description="增强 LLM 配置 ID（MQE 改写/HyDE 生成用，model_type=2）；空 = 跟随对话模型")
    rerank_config_id: UUID | None = Field(
        None, description="Rerank 模型配置 ID（model_type=3）；空 = 用 config.yaml tools.rerank 全局默认")
    system_prompt: str | None = Field(None, description="系统提示词，不传则使用默认 RAG 模板")
    temperature: float | None = Field(None, ge=0.0, le=2.0, description="采样温度；空 = 跟随模型配置（模型也未配置时默认 0.7）")
    top_p: float | None = Field(None, ge=0.0, le=1.0, description="核采样；空 = 跟随模型配置（模型也未配置时默认 0.9）")
    max_tokens: int | None = Field(None, ge=1, le=1000000, description="最大生成 token 数；空 = 跟随模型配置/厂商默认")
    welcome_message: str | None = Field(None, max_length=500)


class GeneralAgentCreate(BaseModel):
    """综合 Agent：能力以工具列表注册"""
    type: Literal["general"] = "general"
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = None
    llm_config_id: UUID = Field(..., description="LLM 模型配置 ID（model_type=2）")
    summary_llm_config_id: UUID | None = Field(
        None, description="总结模型配置 ID（model_type=2）；空 = 跟随对话模型")
    tools: list[ToolConfig] = Field(..., min_length=1, description="工具配置列表，至少一个工具")
    enhance_llm_config_id: UUID | None = Field(
        None, description="增强 LLM 配置 ID（MQE 改写/HyDE 生成用，model_type=2）；空 = 跟随对话模型")
    rerank_config_id: UUID | None = Field(
        None, description="Rerank 模型配置 ID（model_type=3）；空 = 用 config.yaml tools.rerank 全局默认")
    system_prompt: str | None = Field(None, description="系统提示词，不传则使用默认 RAG 模板")
    temperature: float | None = Field(None, ge=0.0, le=2.0, description="采样温度；空 = 跟随模型配置（模型也未配置时默认 0.7）")
    top_p: float | None = Field(None, ge=0.0, le=1.0, description="核采样；空 = 跟随模型配置（模型也未配置时默认 0.9）")
    max_tokens: int | None = Field(None, ge=1, le=1000000, description="最大生成 token 数；空 = 跟随模型配置/厂商默认")
    welcome_message: str | None = Field(None, max_length=500)


AgentCreate = Annotated[
    Union[SimpleRagAgentCreate, GeneralAgentCreate],
    Field(discriminator="type"),
]


# ── 编辑请求（统一结构，全部可选）──────

class AgentUpdate(BaseModel):
    """编辑 Agent（全部可选；type 不可改，后端按库中类型更新对应表）"""
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    llm_config_id: UUID | None = None
    summary_llm_config_id: UUID | None = None
    kb_id: UUID | None = Field(None, description="simple_rag 类型专用")
    top_k: int | None = Field(None, ge=1, le=50)
    score_threshold: float | None = Field(None, ge=0.0, le=1.0)
    tools: list[ToolConfig] | None = Field(None, min_length=1, description="general 类型专用，整体替换")
    # ── Phase 4.6 检索增强 ──
    mqe_enabled: bool | None = None
    hyde_enabled: bool | None = None
    mqe_query_count: int | None = Field(None, ge=2, le=5)
    rerank_enabled: bool | None = None
    enhance_llm_config_id: UUID | None = Field(
        None, description="增强 LLM 配置 ID（model_type=2）；空 = 跟随对话模型")
    rerank_config_id: UUID | None = Field(
        None, description="Rerank 模型配置 ID（model_type=3）；空 = 用 config.yaml tools.rerank 全局默认")
    system_prompt: str | None = None
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    top_p: float | None = Field(None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(None, ge=1, le=1000000)
    welcome_message: str | None = Field(None, max_length=500)
    status: int | None = Field(None, ge=0, le=9)
    # ── 嵌入治理参数（agent_index 表，数据库动态可改）──
    rate_limit_per_min: int | None = Field(None, ge=1, le=10000,
                                           description="公开接口限流（次/分钟）")
    allowed_domains: list[str] | None = Field(
        None, description="嵌入域名白名单，空数组=不限制")
    anonymous_retention_days: int | None = Field(
        None, ge=0, le=3650, description="匿名会话保留天数")


# ── 响应 ────────────────────────────────

class AgentResponse(BaseModel):
    """Agent 详情/创建/编辑 响应（统一结构，按 type 填充对应字段）"""
    id: UUID
    type: Literal["simple_rag", "general"]
    name: str
    description: str | None
    llm_config_id: UUID | None
    llm_provider: str | None = None
    llm_model: str | None = None
    summary_llm_config_id: UUID | None = None
    kb_id: UUID | None = None
    kb_name: str | None = None
    top_k: int | None = None
    score_threshold: float | None = None
    # ── Phase 4.6 检索增强 ──
    mqe_enabled: bool = False
    hyde_enabled: bool = False
    mqe_query_count: int = 3
    rerank_enabled: bool = False
    enhance_llm_config_id: UUID | None = None
    rerank_config_id: UUID | None = None
    tools: list[ToolConfig] = []
    system_prompt: str
    temperature: float | None
    top_p: float | None
    max_tokens: int | None
    welcome_message: str | None
    status: int
    # ── 嵌入治理参数（agent_index 表）──
    rate_limit_per_min: int = 60
    allowed_domains: list[str] = []
    anonymous_retention_days: int = 30
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class AgentListItem(BaseModel):
    """Agent 列表项（仅表格需要）"""
    id: UUID
    type: Literal["simple_rag", "general"]
    name: str
    description: str | None
    llm_model: str | None = None
    kb_id: UUID | None = None
    kb_name: str | None = None
    tools: list[ToolConfig] = []
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


class BatchAgentAction(BaseModel):
    """批量操作 Agent"""
    ids: list[UUID] = Field(..., min_length=1, max_length=100)
    action: Literal["enable", "disable", "delete"]


# ── 对话 ────────────────────────────────

class ChatMessage(BaseModel):
    """对话历史消息"""
    role: Literal["user", "assistant"]
    content: str = Field(..., min_length=1)


class ChatRequest(BaseModel):
    """对话请求(记忆由服务端 checkpoint 管理,前端不传 history)"""
    message: str = Field(..., min_length=1, max_length=4000)
    conversation_id: UUID | None = Field(
        None, description="会话 ID;缺省时后端自动创建并随响应返回")
    stream: bool = Field(False, description="true=SSE 流式返回")


class Citation(BaseModel):
    """引用来源"""
    chunk_id: UUID
    document_name: str
    content: str
    score: float


class ChatResponse(BaseModel):
    """非流式对话响应"""
    conversation_id: UUID
    answer: str
    citations: list[Citation] = []
