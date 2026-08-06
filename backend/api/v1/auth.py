"""
Phase 1：认证接口（Router 层）

只做三件事：解析请求 → 调用 Service → 返回响应
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.schemas.common import ErrorResponse, SuccessResponse
from backend.schemas.auth import LoginRequest, RefreshRequest, TokenResult
from backend.services import AuthService

router = APIRouter(prefix="/api/v1/auth", tags=["认证"])


@router.post(
    "/login",
    response_model=SuccessResponse[TokenResult],
    responses={401: {"model": ErrorResponse, "description": "用户名或密码错误"}},
    summary="管理员登录",
)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    result = await AuthService.login(db, body.username, body.password)
    return SuccessResponse(result=result)


@router.post(
    "/refresh",
    response_model=SuccessResponse[TokenResult],
    responses={401: {"model": ErrorResponse, "description": "Token 无效或已过期/已撤销"}},
    summary="刷新 Token",
)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_db)):
    result = await AuthService.refresh(db, body.refresh_token)
    return SuccessResponse(result=result)
