from sqlalchemy import Float, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from uuid import UUID

from backend.models.Base import Base


class Agents(Base):
    __tablename__ = "agents"
    __table_args__ = {"comment": "Agent 表：绑定一个知识库 + 一个 LLM 模型配置的可对话实体"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="创建者用户 ID"
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="Agent 名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="描述"
    )
    kb_id: Mapped[UUID] = mapped_column(
        ForeignKey("knowledge_bases.id"), nullable=False, comment="绑定知识库 ID（一对一）"
    )
    llm_config_id: Mapped[UUID] = mapped_column(
        ForeignKey("user_model_config.id"), nullable=False, comment="LLM 模型配置 ID（model_type=2）"
    )
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, comment="系统提示词（RAG 模板，可编辑）"
    )
    top_k: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False, comment="检索返回块数"
    )
    score_threshold: Mapped[float] = mapped_column(
        Float, default=0.3, nullable=False, comment="相似度阈值（余弦相似度，低于则丢弃）"
    )
    temperature: Mapped[float] = mapped_column(
        Float, default=0.7, nullable=False, comment="LLM 温度"
    )
    top_p: Mapped[float] = mapped_column(
        Float, default=0.9, nullable=False, comment="LLM 核采样"
    )
    welcome_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="欢迎语（Phase 5 浮窗使用）"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="0=禁用, 1=启用, 9=软删除"
    )

    knowledge_base = relationship("KnowledgeBases", lazy="selectin")

    def __repr__(self) -> str:
        return f"<Agents(id={self.id}, name={self.name})>"
