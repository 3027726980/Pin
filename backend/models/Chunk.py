from sqlalchemy import ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID

from backend.models.Base import Base


class Chunk(Base):
    __tablename__ = "chunks"
    __table_args__ = {"comment": "分块表：存储文档分块后的文本片段"}

    document_id: Mapped[UUID] = mapped_column(
        ForeignKey("documents.id"), nullable=False, comment="所属文档 ID"
    )
    kb_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=False, comment="所属知识库 ID（冗余加速检索）"
    )
    chunk_index: Mapped[int] = mapped_column(
        Integer, default=0, nullable=False, comment="块序号，同一文档内从 0 递增"
    )
    content: Mapped[str] = mapped_column(Text, nullable=False, comment="分块文本内容")
    chunk_metadata: Mapped[dict | None] = mapped_column(
        "metadata", JSONB, nullable=True, comment="来源标题、页码等元信息"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=0, nullable=False, comment="-1=失败, 0=未完成, 1=已完成, 2=进行中"
    )

    document = relationship("Document", back_populates="chunks")
    embedding = relationship("Embedding", back_populates="chunk", uselist=False, lazy="selectin")

    def __repr__(self) -> str:
        return f"<Chunk(id={self.id}, doc_id={self.document_id}, index={self.chunk_index})>"
