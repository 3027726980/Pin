"""
知识库 + 文档 请求/响应 Schema

- KnowledgeBaseCreate / Update：创建/编辑请求
- KnowledgeBaseResponse：详情 + 创建/编辑 响应（完整字段）
- KnowledgeBaseListItem：列表响应（精简，仅表格需要）
- DocumentResponse：上传响应（完整）
- DocumentListItem：文件列表响应（精简）
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


# ── 知识库 ────────────────────────────

class KnowledgeBaseCreate(BaseModel):
    """创建知识库"""
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None)
    allowed_extensions: str | None = Field(None, max_length=500)
    max_file_size: int | None = Field(None, ge=1, description="单文件上限（字节），不传则使用 config.yaml 默认值")
    allow_multiple: bool = Field(True)


class KnowledgeBaseUpdate(BaseModel):
    """编辑知识库（全部可选）"""
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    allowed_extensions: str | None = Field(None, max_length=500)
    max_file_size: int | None = Field(None, ge=1)
    allow_multiple: bool | None = None


class KnowledgeBaseResponse(BaseModel):
    """知识库详情/编辑 响应（编辑弹窗回填需要）"""
    id: UUID
    name: str
    description: str | None
    allowed_extensions: str | None
    max_file_size: int
    allow_multiple: bool
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeBaseListItem(BaseModel):
    """知识库列表项（仅表格需要）"""
    id: UUID
    name: str
    allowed_extensions: str | None
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 文档 ──────────────────────────────

class DocumentResponse(BaseModel):
    """文档详情/上传 响应（完整字段）"""
    id: UUID
    knowledge_base_id: UUID
    user_id: UUID
    filename: str
    file_path: str
    file_size: int
    file_type: str | None
    status: int
    is_chunked: bool
    is_vectorized: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DocumentListItem(BaseModel):
    """文件列表项（仅表格需要）"""
    id: UUID
    filename: str
    file_size: int
    file_type: str | None
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 分页 ──────────────────────────────

class PaginatedResponse(BaseModel):
    """分页响应"""
    items: list
    total: int
    page: int
    page_size: int
