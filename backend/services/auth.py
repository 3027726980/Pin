"""
认证业务逻辑

登录流程：验密 → 签发 Token → 写入白名单
刷新流程：验旧 Token → 删旧白名单 → 签新 Token → 写新白名单
"""

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
)
from backend.repositories import TokenWhitelistRepo, UserRepo
from backend.schemas.auth import TokenResult


class AuthService:
    """认证业务逻辑 —— 不依赖 HTTP 请求/响应，只处理数据和规则"""

    @staticmethod
    async def login(db: AsyncSession, username: str, password: str) -> TokenResult:
        # 1. 查用户
        user = await UserRepo.get_by_username(db, username)
        if user is None or not verify_password(password, user.hashed_password):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not user.is_active:
            raise HTTPException(status_code=401, detail="账号已被禁用")

        # 2. 清理该用户所有旧 Token（确保一个用户只有一套有效凭证）
        await TokenWhitelistRepo.delete_all_access_for_user(db, user.id)
        await TokenWhitelistRepo.delete_all_refresh_for_user(db, user.id)

        # 3. 签发新 Token
        access_token, access_jti = create_access_token(str(user.id))
        refresh_token, refresh_jti = create_refresh_token(str(user.id))

        # 4. 写白名单
        await TokenWhitelistRepo.add_access(
            db, user.id, access_jti,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.jwt.access_token_expire),
        )
        await TokenWhitelistRepo.add_refresh(
            db, user.id, refresh_jti,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt.refresh_token_expire),
        )
        await db.commit()

        return TokenResult(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt.access_token_expire * 60,
        )

    @staticmethod
    async def refresh(db: AsyncSession, refresh_token_str: str) -> TokenResult:
        # 1. 解码
        payload = decode_token(refresh_token_str)
        if payload is None:
            raise HTTPException(status_code=401, detail="Token 无效或已过期")
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail="Token 类型错误，需要 refresh token")

        # 2. 白名单校验
        old_jti = payload.get("jti")
        if await TokenWhitelistRepo.find_valid_refresh(db, old_jti) is None:
            raise HTTPException(status_code=401, detail="Token 已被撤销")

        # 3. 用户状态
        user = await UserRepo.get_by_id(db, payload.get("sub"))
        if user is None or not user.is_active:
            raise HTTPException(status_code=401, detail="用户不存在或已被禁用")

        # 4. 签发新 Token
        new_access, new_access_jti = create_access_token(str(user.id))
        new_refresh, new_refresh_jti = create_refresh_token(str(user.id))

        # 5. 白名单更新（删旧 + 插新）
        await TokenWhitelistRepo.delete_refresh(db, old_jti)
        await TokenWhitelistRepo.delete_all_access_for_user(db, user.id)
        await TokenWhitelistRepo.add_access(
            db, user.id, new_access_jti,
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=settings.jwt.access_token_expire),
        )
        await TokenWhitelistRepo.add_refresh(
            db, user.id, new_refresh_jti,
            expires_at=datetime.now(timezone.utc) + timedelta(days=settings.jwt.refresh_token_expire),
        )
        await db.commit()

        return TokenResult(
            access_token=new_access,
            refresh_token=new_refresh,
            expires_in=settings.jwt.access_token_expire * 60,
        )
