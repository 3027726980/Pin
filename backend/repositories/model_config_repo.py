"""
模型配置数据访问
"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ModelConfig


class ModelConfigRepo:
    """模型配置 CRUD"""

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        model_type: int,
        provider: str,
        model_name: str,
        key_value: str | None,
        is_active: bool = True,
    ) -> ModelConfig:
        cfg = ModelConfig(
            user_id=user_id,
            model_type=model_type,
            provider=provider,
            model_name=model_name,
            key_value=key_value,
            is_active=is_active,
        )
        db.add(cfg)
        await db.flush()
        return cfg

    @staticmethod
    async def get_by_id(db: AsyncSession, cfg_id: UUID) -> ModelConfig | None:
        return await db.get(ModelConfig, cfg_id)

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user_id: UUID,
    ) -> list[ModelConfig]:
        q = (
            select(ModelConfig)
            .where(ModelConfig.user_id == user_id)
            .order_by(ModelConfig.model_type, ModelConfig.created_at.desc())
        )
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def update(
        db: AsyncSession,
        cfg: ModelConfig,
        **kwargs,
    ) -> ModelConfig:
        for key, value in kwargs.items():
            if value is not None:
                setattr(cfg, key, value)
        await db.flush()
        return cfg

    @staticmethod
    async def delete(db: AsyncSession, cfg: ModelConfig) -> None:
        await db.delete(cfg)
        await db.flush()
