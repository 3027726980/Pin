"""
Access Token 白名单

- 只有此表中的 Access Token 才被视为有效
- 刷新或登出时删除旧记录，实现即时失效
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, String
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class AccessTokenWhitelist(Base):
    __tablename__ = "access_token_whitelist"
    __table_args__ = {"comment": "Access Token 白名单：只存当前有效的 Access Token"}

    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
        comment="所属用户 ID",
    )
    token_jti: Mapped[str] = mapped_column(
        String(36), unique=True, nullable=False, comment="JWT ID，与 Token payload 中的 jti 一致"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, comment="过期时间，超时后即使未删除也视为无效"
    )

    def __repr__(self) -> str:
        return f"<AccessTokenWhitelist(id={self.id}, user_id={self.user_id})>"
