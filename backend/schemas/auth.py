"""
Phase 1 认证相关 Schema
"""

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    """管理员登录请求"""
    username: str = Field(..., min_length=1, max_length=100, examples=["admin"])
    password: str = Field(..., min_length=1, max_length=128, examples=["your-password"])


class RefreshRequest(BaseModel):
    """刷新 Token 请求"""
    refresh_token: str = Field(..., min_length=1)


class TokenResult(BaseModel):
    """Token 响应数据"""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int  # Access Token 有效期（秒）
