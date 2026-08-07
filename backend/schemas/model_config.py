"""
模型配置 请求/响应 Schema
"""
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class ModelConfigCreate(BaseModel):
    """创建模型配置"""
    model_type: int = Field(..., ge=1, le=9)
    provider: str = Field(..., max_length=50)
    model_name: str = Field(..., max_length=200)
    key_value: str | None = Field(None, max_length=500)
    is_active: bool = True


class ModelConfigUpdate(BaseModel):
    """编辑模型配置（全部可选）"""
    model_type: int | None = Field(None, ge=1, le=9)
    provider: str | None = Field(None, max_length=50)
    model_name: str | None = Field(None, max_length=200)
    key_value: str | None = Field(None, max_length=500)
    is_active: bool | None = None


class ModelConfigResponse(BaseModel):
    """模型配置响应"""
    id: UUID
    user_id: UUID
    model_type: int
    provider: str
    model_name: str
    key_value: str | None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}
