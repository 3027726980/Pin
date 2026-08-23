from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from backend.models.Base import Base


class UserProviders(Base):
    """用户自定义厂商：前端可增删改，效果等同 config.yaml 预置厂商"""

    __tablename__ = "user_providers"
    __table_args__ = {"comment": "用户自定义厂商表：带调用模式，可挂模型配置"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, comment="所属用户 ID"
    )
    name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="厂商名（同用户下唯一）"
    )
    protocol: Mapped[str] = mapped_column(
        String(20), default="openai", nullable=False, comment="调用模式（协议）：openai 等"
    )
    base_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="厂商默认接口地址（自定义厂商必填，模型配置创建时自动继承，可覆盖）"
    )
    description: Mapped[str | None] = mapped_column(
        String(200), nullable=True, comment="备注说明"
    )

    def __repr__(self) -> str:
        return f"<UserProviders(id={self.id}, name={self.name})>"
