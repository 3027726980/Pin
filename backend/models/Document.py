from sqlalchemy import BigInteger, Boolean, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID

from backend.models.Base import Base


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = {"comment": "文档表：存储上传到知识库中的文件元信息"}

    knowledge_base_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=False, comment="所属知识库 ID"
    )
    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="上传者用户 ID"
    )
    filename: Mapped[str] = mapped_column(
        String(500), nullable=False, comment="原始文件名"
    )
    file_path: Mapped[str] = mapped_column(
        String(1000),
        nullable=False,
        comment="相对路径，如 uploads/{kb_id}/{name}_{uuid}.{ext}",
    )
    file_size: Mapped[int] = mapped_column(
        BigInteger, nullable=False, comment="文件大小（字节）"
    )
    file_type: Mapped[str | None] = mapped_column(
        String(100), nullable=True, comment="文件后缀，如 .pdf，无后缀则为 NULL"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="0=禁用, 1=启用, 9=逻辑删除"
    )
    is_chunked: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已完成切片"
    )
    is_vectorized: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="是否已完成向量化"
    )

    knowledge_base = relationship("KnowledgeBase", back_populates="documents")

    def __repr__(self) -> str:
        return f"<Document(id={self.id}, filename={self.filename})>"
