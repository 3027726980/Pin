from sqlalchemy import ForeignKey, SmallInteger
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID

from pgvector.sqlalchemy import Vector

from backend.models.Base import Base


class Embeddings(Base):
    __tablename__ = "embeddings"
    __table_args__ = {"comment": "向量表：存储分块文本的 Embedding 向量，整体 vector(4096)"}

    chunk_id: Mapped[UUID] = mapped_column(
        ForeignKey("chunks.id"), unique=True, nullable=False, comment="关联的分块 ID，一一对应"
    )
    kb_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=False, comment="所属知识库 ID（冗余加速检索）"
    )
    embedding: Mapped[list[float] | None] = mapped_column(
        Vector(4096), nullable=True, comment="向量数据，固定 4096 维（小维度零填充）"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="0=禁用, 1=启用, 9=软删除（与关联 chunk 状态同步）"
    )

    chunk = relationship("Chunks", back_populates="embedding")

    def __repr__(self) -> str:
        return f"<Embeddings(id={self.id}, chunk_id={self.chunk_id})>"
