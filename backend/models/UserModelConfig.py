from sqlalchemy import Boolean, Float, ForeignKey, SmallInteger, String
from sqlalchemy.orm import Mapped, mapped_column
from uuid import UUID

from backend.models.Base import Base


class UserModelConfig(Base):
    __tablename__ = "user_model_config"
    __table_args__ = {"comment": "用户模型配置表：用户在前端创建，可覆盖默认参数"}

    user_id: Mapped[UUID] = mapped_column(
        ForeignKey("users.id"), nullable=False, comment="所属用户 ID"
    )
    provider: Mapped[str] = mapped_column(
        String(50), nullable=False, comment="厂商名"
    )
    model_name: Mapped[str] = mapped_column(
        String(200), nullable=False, comment="模型名"
    )
    model_type: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, comment="1=embedding, 2=LLM"
    )
    base_url: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="用户可覆盖，NULL 则用默认"
    )
    api_key: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="用户填的 API Key"
    )
    dimension: Mapped[int | None] = mapped_column(
        nullable=True, comment="embedding 维度"
    )
    protocol: Mapped[str | None] = mapped_column(
        String(20), nullable=True, comment="调用模式（协议）：openai 等；NULL = 按厂商推断默认 openai"
    )
    # ── Phase 4.8 采样参数（可空 = 未配置，Agent 未单独设置时生效）──
    temperature: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="采样温度（默认 0.7）"
    )
    top_p: Mapped[float | None] = mapped_column(
        Float, nullable=True, comment="核采样（默认 0.9）"
    )
    max_tokens: Mapped[int | None] = mapped_column(
        nullable=True, comment="最大生成 token 数（空 = 厂商默认）"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, default=True, nullable=False, comment="是否启用"
    )
