"""
全局依赖：提取 Bearer Token → 白名单校验 → 返回当前用户

Phase 2+ 的所有业务接口统一使用 get_current_user 注入当前登录用户。
"""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.security import decode_token
from backend.repositories import TokenWhitelistRepo, UserRepo

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
):
    """
    校验流程：
    1. 提取 Authorization: Bearer <token>
    2. 解码 JWT，验证签名 + 过期
    3. 检查 type == "access"
    4. 查 access_token_whitelist（jti 存在且未过期 → 有效）
    5. 查用户存在且启用
    6. 返回 User 对象
    """
    if credentials is None:
        raise HTTPException(status_code=401, detail="缺少认证信息")

    token = credentials.credentials

    # 解码
    payload = decode_token(token)
    if payload is None:
        raise HTTPException(status_code=401, detail="Token 无效或已过期")

    if payload.get("type") != "access":
        raise HTTPException(status_code=401, detail="Token 类型错误，需要 access token")

    # 白名单校验
    jti = payload.get("jti")
    if await TokenWhitelistRepo.find_valid_access(db, jti) is None:
        raise HTTPException(status_code=401, detail="Token 已被撤销或不存在")

    # 用户状态
    user = await UserRepo.get_by_id(db, payload.get("sub"))
    if user is None or not user.is_active:
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

    return user
