from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from backend.models.Base import Base


class UserModelConfig(Base):
    __tablename__ = "user_model_config"
    __table_args__ = {"comment": "用户模型配置表：用户在前端创建，可覆盖默认参数"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="所属用户 ID"
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="厂商名"
    )
    model_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="模型名"
    )
    model_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="1=embedding, 2=LLM"
    )
    base_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="用户可覆盖，NULL 则用默认"
    )
    api_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="用户填的 API Key"
    )
    dimension: Mapped[int | None] = mapped_column(
        nullable=True, comment="embedding 维度"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否启用"
    )
