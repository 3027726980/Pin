"""会话消息留痕：与 checkpoint 解耦，历史查看走此表"""
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, SmallInteger, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class Messages(Base):
    """会话消息：每轮问答落库（含引用），用户历史查看的数据源"""

    __tablename__ = "messages"
    __table_args__ = {"comment": "会话消息表：历史留痕（与 checkpoint 解耦）"}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, comment="消息 ID"
    )
    conversation_id: Mapped[UUID] = mapped_column(
        ForeignKey("conversations.id"), nullable=False, index=True,
        comment="归属会话 ID",
    )
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="user / assistant"
    )
    content: Mapped[str] = mapped_column(
        Text, nullable=False, comment="消息内容"
    )
    citations: Mapped[list | None] = mapped_column(
        JSONB, nullable=True, comment="助手回答的引用来源（user 消息为 null）"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="1=正常, 9=软删除"
    )

    def __repr__(self) -> str:
        return f"<Messages(id={self.id}, role={self.role})>"
