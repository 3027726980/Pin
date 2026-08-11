"""会话实体：id 即 checkpoint 的 thread_id"""
from uuid import UUID, uuid4

from sqlalchemy import ForeignKey, SmallInteger, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class Conversations(Base):
    """会话：对话记忆的归属单元，id 作为 LangGraph checkpoint 的 thread_id

    归属规则：登录会话 user_id 非空 + client_id 空；匿名会话 user_id 空 + client_id 非空。
    """

    __tablename__ = "conversations"
    __table_args__ = {"comment": "会话表：id 即 checkpoint thread_id"}

    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, default=uuid4, comment="会话 ID（= thread_id）"
    )
    user_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True,
        comment="归属用户 ID（匿名会话为空）",
    )
    agent_id: Mapped[UUID] = mapped_column(
        ForeignKey("agent_index.id"), nullable=False, index=True,
        comment="归属 Agent ID",
    )
    client_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True, comment="匿名访客标识（登录会话为空）"
    )
    title: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="会话标题（取首条用户消息前 10 字）"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="1=启用, 9=软删除"
    )

    def __repr__(self) -> str:
        return f"<Conversations(id={self.id}, agent_id={self.agent_id})>"
