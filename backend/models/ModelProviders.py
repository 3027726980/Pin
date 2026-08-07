from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class ModelProviders(Base):
    __tablename__ = "model_providers"
    __table_args__ = {"comment": "模型厂商表：启动时从 config.yaml 自动创建，用户只读"}

    name: Mapped[str] = mapped_column(
        String(50), unique=True, nullable=False, comment="厂商名：aliyun / openai"
    )

    def __repr__(self) -> str:
        return f"<ModelProviders(name={self.name})>"
