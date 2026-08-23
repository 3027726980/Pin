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
    protocol: str = Field("openai", max_length=20, description="调用模式（协议）：取自 config.yaml protocols 节点")
    base_url: str = Field(..., max_length=500, description="厂商默认接口地址（必填）")
    description: str | None = Field(None, max_length=200)


class ProviderUpdate(BaseModel):
    """编辑自定义厂商（全部可选）"""
    name: str | None = Field(None, min_length=1, max_length=50)
    protocol: str | None = Field(None, max_length=20)
    base_url: str | None = Field(None, max_length=500)
    description: str | None = Field(None, max_length=200)


class ProviderResponse(BaseModel):
    """厂商（预置 + 自定义合并）"""
    id: UUID | None = Field(None, description="自定义厂商才有 id（预置为 None）")
    name: str
    protocol: str
    base_url: str | None = None
    description: str | None = None
    source: Literal["preset", "custom"] = "preset"
    model_count: int = 0
    created_at: datetime | None = None
