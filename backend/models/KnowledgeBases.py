from sqlalchemy import BigInteger, Boolean, ForeignKey, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID

from backend.models.Base import Base


class KnowledgeBases(Base):
    __tablename__ = "knowledge_bases"
    __table_args__ = {"comment": "知识库表：存储知识库配置和上传约束"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="创建者用户 ID"
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False, comment="知识库名称")
    description: Mapped[str | None] = mapped_column(Text, nullable=True, comment="描述")
    allowed_extensions: Mapped[str | None] = mapped_column(
        String(500),
        nullable=True,
        comment="允许的文件后缀，逗号分隔如 .pdf,.txt,.md；为空则允许所有类型",
    )
    max_file_size: Mapped[int] = mapped_column(
        BigInteger,
        default=104857600,
        nullable=False,
        comment="单文件大小上限（字节），默认 104857600 = 100MB",
    )
    allow_multiple: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否允许多文件上传"
    )
    chunk_size: Mapped[int] = mapped_column(
        default=800, nullable=False, comment="分块大小（字符数），默认 800"
    )
    chunk_overlap: Mapped[int] = mapped_column(
        default=150, nullable=False, comment="相邻块重叠字符数，默认 150"
    )
    chunk_separators: Mapped[str] = mapped_column(
        String(300),
        default="\n##,\n###,\n,。,., ",
        nullable=False,
        comment="递归分隔符（逗号分隔）",
    )
    embedding_model: Mapped[str] = mapped_column(
        String(100),
        default="text-embedding-3-small",
        nullable=False,
        comment="选用的 Embedding 模型",
    )
    embedding_dimension: Mapped[int] = mapped_column(
        default=1536, nullable=False, comment="模型输出维度"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="0=禁用, 1=启用, 9=逻辑删除"
    )

    documents = relationship("Documents", back_populates="knowledge_base", lazy="selectin")

    def __repr__(self) -> str:
        return f"<KnowledgeBases(id={self.id}, name={self.name})>"
