"""
用户模型配置 业务逻辑
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import UserModelConfigRepo
from backend.schemas.user_model_config import (
    UserModelConfigCreate,
    UserModelConfigResponse,
    UserModelConfigUpdate,
    DefaultModelConfigResponse,
)


class UserModelConfigService:

    @staticmethod
    async def list_defaults(db: AsyncSession) -> list[DefaultModelConfigResponse]:
        items = await UserModelConfigRepo.list_default_configs(db)
        return [DefaultModelConfigResponse.model_validate(c) for c in items]

    @staticmethod
    async def list_by_user(db: AsyncSession, user: Users) -> list[UserModelConfigResponse]:
        items = await UserModelConfigRepo.list_by_user(db, user.id)
        return [UserModelConfigResponse.model_validate(c) for c in items]

    @staticmethod
    async def create(db: AsyncSession, user: Users, data: UserModelConfigCreate) -> UserModelConfigResponse:
        cfg = await UserModelConfigRepo.create(
            db,
            user_id=user.id,
            provider=data.provider,
            model_name=data.model_name,
            model_type=data.model_type,
            base_url=data.base_url,
            api_key=data.api_key,
            dimension=data.dimension,
            is_active=data.is_active,
        )
        await db.commit()
        await db.refresh(cfg)  # 刷新 server_default 填充的 created_at/updated_at
        return UserModelConfigResponse.model_validate(cfg)

    @staticmethod
    async def update(db: AsyncSession, user: Users, cfg_id: UUID, data: UserModelConfigUpdate) -> UserModelConfigResponse:
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id:
            raise HTTPException(status_code=404, detail="配置不存在")
        cfg = await UserModelConfigRepo.update(
            db, cfg,
            provider=data.provider,
            model_name=data.model_name,
            model_type=data.model_type,
            base_url=data.base_url,
            api_key=data.api_key,
            dimension=data.dimension,
            is_active=data.is_active,
        )
        await db.commit()
        await db.refresh(cfg)  # 重新加载 onupdate 触发的 updated_at，避免 MissingGreenlet
        return UserModelConfigResponse.model_validate(cfg)

    @staticmethod
    async def delete(db: AsyncSession, user: Users, cfg_id: UUID) -> None:
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id:
            raise HTTPException(status_code=404, detail="配置不存在")
        await UserModelConfigRepo.delete(db, cfg)
        await db.commit()
