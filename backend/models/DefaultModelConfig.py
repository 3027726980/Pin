from sqlalchemy import ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.models.Base import Base


class DefaultModelConfig(Base):
    __tablename__ = "default_model_config"
    __table_args__ = {"comment": "默认模型配置表：启动时从 config.yaml 自动创建，用户只读"}

    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="厂商名"
    )
    model_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="模型名"
    )
    model_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="1=embedding, 2=LLM（3~9 预留）"
    )
    base_url: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="默认 API 地址"
    )
    dimension: Mapped[int | None] = mapped_column(
        nullable=True, comment="embedding 维度，LLM 为 NULL"
    )
