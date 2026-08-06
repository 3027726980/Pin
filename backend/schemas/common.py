"""
通用响应 Schema —— 所有接口统一使用

成功：SuccessResponse[T]
错误：ErrorResponse
"""

from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class SuccessResponse(BaseModel, Generic[T]):
    """统一成功响应格式"""
    code: int = 200
    message: str = "ok"
    result: T | None = None


class ErrorResponse(BaseModel):
    """统一错误响应格式"""
    code: int
    message: str
    result: None = None
