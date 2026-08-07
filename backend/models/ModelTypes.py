from sqlalchemy import SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column

from backend.models.Base import Base


class ModelTypes(Base):
    __tablename__ = "model_types"
    __table_args__ = {"comment": "模型类型对照表：code → 名称，启动时从 config.yaml 同步"}

    code: Mapped[int] = mapped_column(
        SmallInteger, unique=True, nullable=False, comment="类型编码：1=embedding, 2=LLM..."
    )
    name: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="类型名称"
    )

    def __repr__(self) -> str:
        return f"<ModelTypes(code={self.code}, name={self.name})>"
