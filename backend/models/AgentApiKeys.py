"""Agent 嵌入密钥：API Key 哈希存储，供公开接口鉴权"""
from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class AgentApiKeys(Base):
    """Agent 嵌入密钥表（只存 SHA-256 哈希，明文仅生成时返回一次）"""

    __tablename__ = "agent_api_keys"
    __table_args__ = {"comment": "Agent 嵌入密钥表"}

    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_index.id", ondelete="CASCADE"),
        nullable=False, index=True, comment="归属 Agent ID",
    )
    key_hash: Mapped[str] = mapped_column(
        String(64), nullable=False, comment="SHA-256 哈希"
    )
    key_preview: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="明文前缀预览（如 pin_AbC...，非明文）"
    )
    name: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="备注（如：公司官网客服）"
    )
    enabled: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="1=启用 0=禁用"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True, comment="最后使用时间（用量参考）"
    )

    def __repr__(self) -> str:
        return f"<AgentApiKeys(id={self.id}, agent_id={self.agent_id})>"
