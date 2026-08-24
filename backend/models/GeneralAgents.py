from sqlalchemy import Boolean, Float, ForeignKey, SmallInteger, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from backend.models.Base import Base


class GeneralAgents(Base):
    """综合 Agent：RAG 等能力以工具形式注册，可组合多个工具"""

    __tablename__ = "general_agents"
    __table_args__ = {"comment": "综合 Agent 表：能力以工具列表（tools JSONB）形式注册"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="创建者用户 ID"
    )
    name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="Agent 名称"
    )
    description: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="描述"
    )
    llm_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="LLM 模型配置 ID（model_type=2，配置删除后为 NULL）"
    )
    summary_llm_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="总结模型配置 ID（SummarizationMiddleware 用，空=跟随对话模型）"
    )
    # ── Phase 4.6 检索增强（Agent 级模型引用）──
    enhance_llm_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="增强 LLM 配置 ID（MQE 改写/HyDE 生成用，model_type=2，空=跟随对话模型）"
    )
    rerank_config_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("user_model_config.id", ondelete="SET NULL"), nullable=True, comment="Rerank 模型配置 ID（model_type=3，空=用 config.yaml tools.rerank 全局默认）"
    )
    tools: Mapped[list] = mapped_column(
        JSONB, default=list, nullable=False,
        comment='工具配置列表：[{"type": "rag", "kb_id": "...", "top_k": 5, "score_threshold": 0.3}]',
    )
    # ── 意图路由 + 内置推理工具（Phase 4.10）──
    intent_rules: Mapped[dict] = mapped_column(
        JSONB, default=dict, nullable=False,
        comment='意图识别规则集：[{"name": "问候语", "kind": "keyword", "keywords": [...], "target": "simple", "priority": 10}]',
    )
    intent_routing: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False, comment="意图路由开关：false=纯 ReAct；true=规则+LLM 兜底分类"
    )
    plan_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="注册 plan 工具（复杂任务规划）"
    )
    reflect_enabled: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="注册 reflect 工具（答案反思）"
    )
    system_prompt: Mapped[str] = mapped_column(
        Text, nullable=False, comment="系统提示词（RAG 模板，可编辑）"
    )
    temperature: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="LLM 温度（空 = 跟随模型配置）"
    )
    top_p: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="LLM 核采样（空 = 跟随模型配置）"
    )
    max_tokens: Mapped[int | None] = mapped_column(
        nullable=True, comment="最大生成 token 数（空 = 跟随模型配置/厂商默认）"
    )
    welcome_message: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="欢迎语（Phase 5 浮窗使用）"
    )
    status: Mapped[int] = mapped_column(
        SmallInteger, default=1, nullable=False, comment="0=禁用, 1=启用, 9=软删除"
    )

    def __repr__(self) -> str:
        return f"<GeneralAgents(id={self.id}, name={self.name})>"
