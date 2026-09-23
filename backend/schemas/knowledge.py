"""
知识库 + 文档 请求/响应 Schema

- KnowledgeBaseCreate / Update：创建/编辑请求
- KnowledgeBaseResponse：详情 + 创建/编辑 响应（完整字段）
- KnowledgeBaseListItem：列表响应（精简，仅表格需要）
- DocumentResponse：上传响应（完整）
- DocumentListItem：文件列表响应（精简）
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from backend.schemas.cleaning import CleaningConfig


# ── 知识库 ────────────────────────────

class KnowledgeBaseCreate(BaseModel):
    """创建知识库"""
    name: str = Field(..., min_length=1, max_length=200)
    description: str | None = Field(None)
    allowed_extensions: str | None = Field(None, max_length=500)
    max_file_size: int | None = Field(None, ge=1, description="单文件上限（字节），不传则使用 config.yaml 默认值")
    allow_multiple: bool = Field(True)
    auto_process: bool | None = Field(None, description="上传后自动处理；不传则复制当前系统的新建默认值")
    chunk_size: int | None = Field(None, ge=50, le=10000)
    chunk_overlap: int | None = Field(None, ge=0, le=9999)
    chunk_separators: str | None = None
    cleaning_config: CleaningConfig | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    user_model_config_id: UUID | None = Field(None, description="关联的用户模型配置，NULL 则使用本地默认 Embedding 模型")

    @model_validator(mode="after")
    def validate_chunk_config(self) -> "KnowledgeBaseCreate":
        """确保重叠长度小于单片长度。"""
        if (
            self.chunk_size is not None
            and self.chunk_overlap is not None
            and self.chunk_overlap >= self.chunk_size
        ):
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self


class KnowledgeBaseUpdate(BaseModel):
    """编辑知识库（全部可选）"""
    name: str | None = Field(None, min_length=1, max_length=200)
    description: str | None = None
    allowed_extensions: str | None = Field(None, max_length=500)
    max_file_size: int | None = Field(None, ge=1)
    allow_multiple: bool | None = None
    auto_process: bool | None = None
    chunk_size: int | None = Field(None, ge=50, le=10000)
    chunk_overlap: int | None = Field(None, ge=0, le=9999)
    chunk_separators: str | None = None
    cleaning_config: CleaningConfig | None = None
    embedding_model: str | None = None
    embedding_dimension: int | None = None
    user_model_config_id: UUID | None = None
    status: int | None = Field(None, ge=0, le=9)

    @model_validator(mode="after")
    def validate_chunk_config(self) -> "KnowledgeBaseUpdate":
        """当两个切片参数同时提交时，确保重叠长度小于单片长度。"""
        if (
            self.chunk_size is not None
            and self.chunk_overlap is not None
            and self.chunk_overlap >= self.chunk_size
        ):
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self


class KnowledgeBaseResponse(BaseModel):
    """知识库详情/编辑 响应（编辑弹窗回填需要）"""
    id: UUID
    name: str
    description: str | None
    allowed_extensions: str | None
    max_file_size: int
    allow_multiple: bool
    auto_process: bool
    chunk_size: int
    chunk_overlap: int
    chunk_separators: str
    cleaning_config: dict
    embedding_model: str
    embedding_dimension: int
    user_model_config_id: UUID | None
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


class KnowledgeBaseListItem(BaseModel):
    """知识库列表项（仅表格需要）"""
    id: UUID
    name: str
    allowed_extensions: str | None
    user_model_config_id: UUID | None = None
    embedding_model: str = ""
    status: int
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 文档 ──────────────────────────────

class ProcessingConfig(BaseModel):
    """可用于知识库或单个文件的完整清洗与切片策略。"""

    cleaning_config: CleaningConfig
    chunk_size: int = Field(..., ge=50, le=10000)
    chunk_overlap: int = Field(..., ge=0, le=9999)
    chunk_separators: str

    @model_validator(mode="after")
    def validate_chunk_config(self) -> "ProcessingConfig":
        """确保重叠长度小于单片长度。"""
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap 必须小于 chunk_size")
        return self


class DocumentProcessingStrategyUpdate(BaseModel):
    """切换文件策略继承模式，或保存一份完整的文件独立策略。"""

    mode: Literal["inherit", "custom"]
    cleaning_config: CleaningConfig | None = None
    chunk_size: int | None = Field(None, ge=50, le=10000)
    chunk_overlap: int | None = Field(None, ge=0, le=9999)
    chunk_separators: str | None = None

    @model_validator(mode="after")
    def validate_mode_payload(self) -> "DocumentProcessingStrategyUpdate":
        """inherit 不接受独立字段；custom 必须提供完整且有效的策略。"""
        fields = (
            self.cleaning_config,
            self.chunk_size,
            self.chunk_overlap,
            self.chunk_separators,
        )
        if self.mode == "inherit":
            if any(value is not None for value in fields):
                raise ValueError("inherit 模式不能携带 custom 策略字段")
            return self
        if any(value is None for value in fields):
            raise ValueError("custom 模式必须提供完整处理策略")
        ProcessingConfig(
            cleaning_config=self.cleaning_config,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            chunk_separators=self.chunk_separators,
        )
        return self

    def to_processing_config(self) -> ProcessingConfig | None:
        """将 custom 请求转换为规范策略；inherit 返回 None。"""
        if self.mode == "inherit":
            return None
        return ProcessingConfig(
            cleaning_config=self.cleaning_config,
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            chunk_separators=self.chunk_separators,
        )

class PreviewChunk(BaseModel):
    """仅用于前端预览的内存切片。"""

    index: int
    content: str
    char_count: int
    overlap_char_count: int = 0


class DocumentPreview(BaseModel):
    """未落库的文档清洗与切片预览。"""

    document_id: UUID
    filename: str
    raw_content: str
    cleaned_content: str
    chunks: list[PreviewChunk]
    cleaning_config_hash: str
    warnings: list[str] = Field(default_factory=list)


class DocumentPreviewSource(BaseModel):
    """供浏览器本地清洗和切片的原始解析文本。"""

    document_id: UUID
    filename: str
    raw_content: str
    algorithm_version: int
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)


class StoredChunkItem(BaseModel):
    """数据库当前生效切片的安全展示结构，不包含向量。"""

    id: UUID
    index: int
    content: str
    char_count: int
    metadata: dict | None = None
    is_vectorized: int


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
    is_parsed: int
    is_cleaned: int
    is_chunked: int
    is_vectorized: int
    cleaned_content: str | None = None
    cleaning_config_hash: str | None = None
    last_error: str | None = None
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
    is_parsed: int
    is_cleaned: int
    is_chunked: int
    is_vectorized: int
    processing_config: ProcessingConfig | None = None
    strategy_mode: Literal["inherit", "custom"] = "inherit"
    effective_processing_config: ProcessingConfig | None = None
    strategy_outdated: bool = False
    applied_algorithm_version: int | None = None
    chunk_count: int = 0
    last_error: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── 批量操作 ──────────────────────────────

class BatchKnowledgeBaseAction(BaseModel):
    """批量操作知识库"""
    ids: list[UUID] = Field(..., min_length=1, max_length=100)
    action: Literal["enable", "disable", "delete"]


class BatchFileAction(BaseModel):
    """批量操作文件"""
    ids: list[UUID] = Field(..., min_length=1, max_length=100)
    action: Literal["delete"]


class DocIdsRequest(BaseModel):
    """文档处理请求（解析/分块共用）"""
    doc_ids: list[UUID] = Field(..., min_length=1, max_length=100)


class ProcessDocumentsRequest(DocIdsRequest):
    """将文档处理到指定阶段；服务端自动补齐前置阶段。"""

    target_stage: Literal["parse", "clean", "chunk", "vectorize"] = "vectorize"
    algorithm_version: int = Field(..., ge=1)


class ChunkIdsRequest(BaseModel):
    """向量化请求"""
    chunk_ids: list[UUID] = Field(..., min_length=1, max_length=500)


class ProcessResult(BaseModel):
    """处理结果"""
    processed: int
    total: int


class BatchResult(BaseModel):
    """批量操作结果"""
    success_count: int
    fail_count: int
    failed_ids: list[UUID] = []


# ── 分页 ──────────────────────────────

class PaginatedResponse(BaseModel):
    """分页响应"""
    items: list
    total: int
    page: int
    page_size: int
