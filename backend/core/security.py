"""
JWT 令牌签发/校验 + 密码哈希

Phase 1 MVP：
- Access Token 30min / Refresh Token 7天
- 密码使用 bcrypt 哈希
- JWT 使用 HS256 算法
- 每个 Token 内嵌 jti（JWT ID），配合白名单表实现即时失效

TODO Phase 2+：
- 支持 RS256 非对称签名
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import bcrypt
from jose import JWTError, jwt

from backend.core.config import settings

# ---- 密码哈希 ----

def hash_password(plain: str) -> str:
    """bcrypt 哈希明文密码"""
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt()).decode()


def verify_password(plain: str, hashed: str) -> bool:
    """验证明文密码与哈希是否匹配"""
    return bcrypt.checkpw(plain.encode(), hashed.encode())


# ---- JWT ----

def _create_token(data: dict, expires_delta: timedelta) -> tuple[str, str]:
    """
    内部：签发一个 JWT。

    Returns:
        (token_string, jti)  —— jti 用于存入白名单表
    """
    to_encode = data.copy()
    jti = str(uuid4())
    now = datetime.now(timezone.utc)
    to_encode.update(
        jti=jti,
        iat=now,
        exp=now + expires_delta,
    )
    token = jwt.encode(
        to_encode,
        settings.jwt.secret_key,
        algorithm=settings.jwt.algorithm,
    )
    return token, jti


def create_access_token(subject: str) -> tuple[str, str]:
    """签发 Access Token（30min）。返回 (token, jti)"""
    return _create_token(
        data={"sub": subject, "type": "access"},
        expires_delta=timedelta(minutes=settings.jwt.access_token_expire),
    )


def create_refresh_token(subject: str) -> tuple[str, str]:
    """签发 Refresh Token（7天）。返回 (token, jti)"""
    return _create_token(
        data={"sub": subject, "type": "refresh"},
        expires_delta=timedelta(days=settings.jwt.refresh_token_expire),
    )


def decode_token(token: str) -> dict | None:
    """
    解码并校验 JWT。成功返回 payload（含 jti / sub / type / iat / exp），失败返回 None。
    """
    try:
        payload = jwt.decode(
            token,
            settings.jwt.secret_key,
            algorithms=[settings.jwt.algorithm],
        )
        return payload
    except JWTError:
        return None
