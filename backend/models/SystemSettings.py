"""通用系统设置：key-value 配置存储（JSONB），脱敏规则等系统级配置的唯一事实来源"""
from uuid import UUID, uuid4

from sqlalchemy import String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class SystemSettings(Base):
    """系统设置项：key 唯一，value 为任意 JSON（后端自行解析）"""

    __tablename__ = "system_settings"
    __table_args__ = {"comment": "通用系统设置表（JSON 配置存储）"}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, comment="设置项 ID"
    )
    key: Mapped[str] = mapped_column(
        String(100), nullable=False, unique=True,
        comment="设置项标识（如 logging.redact_rules）",
    )
    value: Mapped[dict] = mapped_column(
        JSONB, nullable=False, comment="配置值（任意 JSON 结构）"
    )
    description: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="设置项说明"
    )

    def __repr__(self) -> str:
        return f"<SystemSettings(key={self.key})>"
