"""
模型配置 业务逻辑
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import User
from backend.repositories import ModelConfigRepo
from backend.schemas.model_config import (
    ModelConfigCreate,
    ModelConfigResponse,
    ModelConfigUpdate,
)


class ModelConfigService:
    """模型配置 CRUD"""

    @staticmethod
    async def list_by_user(
        db: AsyncSession,
        user: User,
    ) -> list[ModelConfigResponse]:
        items = await ModelConfigRepo.list_by_user(db, user.id)
        return [ModelConfigResponse.model_validate(cfg) for cfg in items]

    @staticmethod
    async def create(
        db: AsyncSession,
        user: User,
        data: ModelConfigCreate,
    ) -> ModelConfigResponse:
        cfg = await ModelConfigRepo.create(
            db,
            user_id=user.id,
            model_type=data.model_type,
            provider=data.provider,
            model_name=data.model_name,
            key_value=data.key_value,
            is_active=data.is_active,
        )
        await db.commit()
        return ModelConfigResponse.model_validate(cfg)

    @staticmethod
    async def update(
        db: AsyncSession,
        user: User,
        cfg_id: UUID,
        data: ModelConfigUpdate,
    ) -> ModelConfigResponse:
        cfg = await ModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id:
            raise HTTPException(status_code=404, detail="配置不存在")

        cfg = await ModelConfigRepo.update(
            db, cfg,
            model_type=data.model_type,
            provider=data.provider,
            model_name=data.model_name,
            key_value=data.key_value,
            is_active=data.is_active,
        )
        await db.commit()
        return ModelConfigResponse.model_validate(cfg)

    @staticmethod
    async def delete(
        db: AsyncSession,
        user: User,
        cfg_id: UUID,
    ) -> None:
        cfg = await ModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id:
            raise HTTPException(status_code=404, detail="配置不存在")
        await ModelConfigRepo.delete(db, cfg)
        await db.commit()
