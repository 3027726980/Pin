"""
Token 白名单表数据访问

- access_token_whitelist：只存当前有效的 Access Token
- refresh_token_whitelist：只存当前有效的 Refresh Token
"""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import AccessTokenWhitelist, RefreshTokenWhitelist


class TokenWhitelistRepo:
    """Token 白名单相关数据库操作"""

    # ── Access Token ──────────────────────────────

    @staticmethod
    async def add_access(
        db: AsyncSession,
        user_id: UUID,
        token_jti: str,
        expires_at: datetime,
    ) -> None:
        db.add(AccessTokenWhitelist(
            user_id=user_id,
            token_jti=token_jti,
            expires_at=expires_at,
        ))

    @staticmethod
    async def find_valid_access(
        db: AsyncSession, token_jti: str
    ) -> AccessTokenWhitelist | None:
        result = await db.execute(
            select(AccessTokenWhitelist).where(
                AccessTokenWhitelist.token_jti == token_jti,
                AccessTokenWhitelist.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def delete_all_access_for_user(db: AsyncSession, user_id: UUID) -> None:
        await db.execute(
            delete(AccessTokenWhitelist).where(
                AccessTokenWhitelist.user_id == user_id,
            )
        )

    # ── Refresh Token ─────────────────────────────

    @staticmethod
    async def add_refresh(
        db: AsyncSession,
        user_id: UUID,
        token_jti: str,
        expires_at: datetime,
    ) -> None:
        db.add(RefreshTokenWhitelist(
            user_id=user_id,
            token_jti=token_jti,
            expires_at=expires_at,
        ))

    @staticmethod
    async def find_valid_refresh(
        db: AsyncSession, token_jti: str
    ) -> RefreshTokenWhitelist | None:
        result = await db.execute(
            select(RefreshTokenWhitelist).where(
                RefreshTokenWhitelist.token_jti == token_jti,
                RefreshTokenWhitelist.expires_at > datetime.now(timezone.utc),
            )
        )
        return result.scalar_one_or_none()

    @staticmethod
    async def delete_all_refresh_for_user(db: AsyncSession, user_id: UUID) -> None:
        await db.execute(
            delete(RefreshTokenWhitelist).where(
                RefreshTokenWhitelist.user_id == user_id,
            )
        )

    @staticmethod
    async def delete_refresh(db: AsyncSession, token_jti: str) -> None:
        await db.execute(
            delete(RefreshTokenWhitelist).where(
                RefreshTokenWhitelist.token_jti == token_jti,
            )
        )
