"""
用户自定义厂商 Schema
"""
from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field


class ProviderCreate(BaseModel):
    """添加自定义厂商"""
    name: str = Field(..., min_length=1, max_length=50, description="厂商名（同用户下唯一）")
    protocol: Literal["openai"] = Field("openai", description="调用模式（协议）：目前仅 openai")
    description: str | None = Field(None, max_length=200)


class ProviderUpdate(BaseModel):
    """编辑自定义厂商（全部可选）"""
    name: str | None = Field(None, min_length=1, max_length=50)
    protocol: Literal["openai"] | None = None
    description: str | None = Field(None, max_length=200)


class ProviderResponse(BaseModel):
    """厂商（预置 + 自定义合并）"""
    id: UUID | None = Field(None, description="自定义厂商才有 id（预置为 None）")
    name: str
    protocol: str
    description: str | None = None
    source: Literal["preset", "custom"] = "preset"
    model_count: int = 0
    created_at: datetime | None = None
