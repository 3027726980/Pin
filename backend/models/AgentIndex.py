from sqlalchemy import ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from backend.models.Base import Base


class AgentIndex(Base):
    """Agent 索引表：所有 Agent 的基础信息，id 与类型表共用主键"""

    __tablename__ = "agent_index"
    __table_args__ = {"comment": "Agent 索引表：所有 Agent 的基础信息，id 与类型表共用主键"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="创建者用户 ID"
    )
    type: Mapped[str] = mapped_column(
        String(20), nullable=False, comment="Agent 类型：simple_rag / general / workflow（预留）"
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="Agent 名称（冗余，列表查询免 join 类型表）"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="描述（冗余）"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="0=禁用, 1=启用, 9=软删除"
    )

    def __repr__(self) -> str:
        return f"<AgentIndex(id={self.id}, type={self.type}, name={self.name})>"
