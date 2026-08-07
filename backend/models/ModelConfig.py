from sqlalchemy import Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from backend.models.Base import Base


class ModelConfig(Base):
    __tablename__ = "model_config"
    __table_args__ = {"comment": "模型配置表：统一管理 Embedding 和 LLM 的 API Key 和模型配置"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="所属用户 ID"
    )
    model_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="1=embedding, 2=LLM（3~9 预留）"
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="服务商：openai / ollama"
    )
    model_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="模型名称：text-embedding-3-small / gpt-4o 等"
    )
    key_value: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="API Key（加密存储）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否启用"
    )

    def __repr__(self) -> str:
        return f"<ModelConfig(id={self.id}, type={self.model_type}, model={self.model_name})>"
