from sqlalchemy import BigInteger, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID

from backend.models.Base import Base


class Documents(Base):
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
    is_parsed: Mapped[int] = mapped_column(
        SmallInteger, default=0, nullable=False, comment="解析状态：-1=失败, 0=未完成, 1=已完成, 2=进行中"
    )
    content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="解析后的完整纯文本"
    )
    cleaned_content: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="按知识库清洗规则处理后的完整纯文本"
    )
    is_cleaned: Mapped[int] = mapped_column(
        SmallInteger, default=0, nullable=False, comment="清洗状态：-1=失败, 0=未完成, 1=已完成, 2=进行中"
    )
    cleaning_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="生成 cleaned_content 所用清洗规则的 SHA-256"
    )
    processing_config: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True, comment="文件独立处理策略；NULL 表示继承知识库默认策略"
    )
    applied_processing_config_hash: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="当前生效切片所用完整处理策略的 SHA-256"
    )
    applied_algorithm_version: Mapped[int | None] = mapped_column(
        Integer, nullable=True, comment="当前生效切片所用处理算法版本"
    )
    is_chunked: Mapped[int] = mapped_column(
        SmallInteger, default=0, nullable=False, comment="切片状态：-1=失败, 0=未完成, 1=已完成, 2=进行中"
    )
    is_vectorized: Mapped[int] = mapped_column(
        SmallInteger, default=0, nullable=False, comment="向量化状态：-1=失败, 0=未完成, 1=已完成, 2=进行中"
    )
    last_error: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="最近一次处理失败原因（解析/分块/向量化），重新处理时清空"
    )

    knowledge_base = relationship("KnowledgeBases", back_populates="documents")
    chunks = relationship("Chunks", back_populates="document", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Documents(id={self.id}, filename={self.filename})>"
