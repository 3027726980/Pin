"""
用户模型配置 Schema
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class UserModelConfigCreate(BaseModel):
    """创建用户模型配置"""
    provider: str = Field(..., max_length=50)
    model_name: str = Field(..., max_length=200)
    model_type: int = Field(..., ge=1, le=9)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    dimension: int | None = None
    protocol: Literal["openai"] | None = Field(
        None, description="调用模式（协议）：目前仅 openai；空 = 按厂商推断默认 openai")
    # ── Phase 4.8 采样参数（可空 = 未配置，Agent 未单独设置时生效）──
    temperature: float | None = Field(None, ge=0.0, le=2.0, description="采样温度，默认 0.7")
    top_p: float | None = Field(None, ge=0.0, le=1.0, description="核采样，默认 0.9")
    max_tokens: int | None = Field(None, ge=1, le=1000000, description="最大生成 token 数，空 = 厂商默认")
    is_active: bool = True


class UserModelConfigUpdate(BaseModel):
    """编辑（全部可选）"""
    provider: str | None = Field(None, max_length=50)
    model_name: str | None = Field(None, max_length=200)
    model_type: int | None = Field(None, ge=1, le=9)
    base_url: str | None = Field(None, max_length=500)
    api_key: str | None = Field(None, max_length=500)
    dimension: int | None = None
    protocol: Literal["openai"] | None = Field(
        None, description="调用模式（协议）：目前仅 openai；空 = 按厂商推断")
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    top_p: float | None = Field(None, ge=0.0, le=1.0)
    max_tokens: int | None = Field(None, ge=1, le=1000000)
    is_active: bool | None = None


class UserModelConfigResponse(BaseModel):
    """响应"""
    id: UUID
    user_id: UUID
    provider: str
    model_name: str
    model_type: int
    base_url: str | None
    api_key: str | None
    dimension: int | None
    protocol: str | None = None
    temperature: float | None = None
    top_p: float | None = None
    max_tokens: int | None = None
    is_active: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class DefaultModelConfigResponse(BaseModel):
    """默认模型（只读）"""
    id: UUID
    provider: str
    model_name: str
    model_type: int
    base_url: str
    dimension: int | None

    model_config = {"from_attributes": True}


class ModelConfigTestResponse(BaseModel):
    """配置连通性测试结果"""
    ok: bool
    detail: str
    latency_ms: int
    extra: dict | None = None
