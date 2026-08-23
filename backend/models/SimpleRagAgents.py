from sqlalchemy import Boolean, Float, ForeignKey, Integer, SmallInteger, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from backend.models.Base import Base


class SimpleRagAgents(Base):
    """简单 RAG Agent：仅有知识库检索（RAG）功能，知识库直接绑定为字段"""

    __tablename__ = "simple_rag_agents"
    __table_args__ = {"comment": "简单 RAG Agent 表：仅 RAG 功能，知识库直接绑定"}

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
        ForeignKey("knowledge_bases.id"), nullable=False, comment="绑定的知识库 ID"
    )
    llm_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="LLM 模型配置 ID（model_type=2，配置删除后为 NULL）"
    )
    summary_llm_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="总结模型配置 ID（SummarizationMiddleware 用，空=跟随对话模型）"
    )
    top_k: Mapped[int] = mapped_column(
        Integer, default=5, nullable=False, comment="检索返回块数（默认取 config.yaml tools.default_top_k）"
    )
    score_threshold: Mapped[float] = mapped_column(
        Float, default=0.3, nullable=False, comment="相似度阈值（默认取 config.yaml tools.default_score_threshold）"
    )
    # ── Phase 4.6 检索增强 ──
    mqe_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="多查询扩展（MQE）：LLM 改写多个子问题多路召回（默认取 config.yaml tools.default_mqe_enabled）"
    )
    hyde_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="假设文档嵌入（HyDE）：LLM 生成假设回答文档作为检索线索（默认取 config.yaml tools.default_hyde_enabled）"
    )
    mqe_query_count: Mapped[int] = mapped_column(
        SmallInteger, default=3, nullable=False, comment="MQE 改写子问题数（2~5，默认取 config.yaml tools.default_mqe_query_count）"
    )
    rerank_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="Rerank 精排开关（默认取 config.yaml tools.default_rerank_enabled）"
    )
    enhance_llm_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="增强 LLM 配置 ID（MQE 改写/HyDE 生成用，model_type=2，空=跟随对话模型）"
    )
    rerank_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="Rerank 模型配置 ID（model_type=3，空=用 config.yaml tools.rerank 全局默认）"
    )
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, comment="系统提示词（RAG 模板，可编辑）"
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

    def __repr__(self) -> str:
        return f"<SimpleRagAgents(id={self.id}, name={self.name})>"
