"""
用户自定义厂商 业务逻辑

- 自定义厂商落库（user_providers），效果等同 config.yaml 预置（带 protocol，可挂模型）
- 合并列表：预置（model_providers 表）+ 自定义（user_providers），前端一次拉取
- 删除不拦截已有配置（provider 为字符串解耦），前端提示即可
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models import DefaultModelConfig, ModelProviders, UserModelConfig, Users
from backend.repositories import ProviderRepo
from backend.schemas.providers import (
    ProviderCreate,
    ProviderResponse,
    ProviderUpdate,
)


class ProviderService:

    @staticmethod
    async def list_all(db: AsyncSession, user: Users) -> list[ProviderResponse]:
        """厂商合并列表：预置（config.yaml seed 的 model_providers）+ 自定义（user_providers）

        预置厂商带默认模型数（default_model_config）；自定义厂商带该用户下配置数
        """
        # 预置厂商 + 默认模型数
        preset_q = (
            select(ModelProviders.name, func.count(DefaultModelConfig.id))
            .outerjoin(DefaultModelConfig,
                       DefaultModelConfig.provider == ModelProviders.name)
            .group_by(ModelProviders.name)
        )
        preset_rows = (await db.execute(preset_q)).all()
        result = [
            ProviderResponse(name=name, protocol="openai", source="preset", model_count=count)
            for name, count in preset_rows
        ]
        # 预置厂商协议与 base_url 从 config.yaml 解析（model_providers 表无这些列，config.yaml 是唯一事实来源）
        preset_providers = getattr(settings, "preset_providers", None) or []
        provider_cfg = {p["name"]: p for p in preset_providers}
        for item in result:
            cfg = provider_cfg.get(item.name, {})
            item.protocol = cfg.get("protocol") or "openai"
            item.base_url = cfg.get("base_url") or None

        # 自定义厂商 + 该用户下配置数
        custom = await ProviderRepo.list_by_user(db, user.id)
        if custom:
            q = (
                select(UserModelConfig.provider, func.count())
                .where(
                    UserModelConfig.user_id == user.id,
                    UserModelConfig.provider.in_([p.name for p in custom]),
                )
                .group_by(UserModelConfig.provider)
            )
            cfg_counts = dict((await db.execute(q)).all())
            result.extend([
                ProviderResponse(
                    id=p.id, name=p.name, protocol=p.protocol, base_url=p.base_url,
                    description=p.description, source="custom",
                    model_count=cfg_counts.get(p.name, 0),
                    created_at=p.created_at,
                )
                for p in custom
            ])
        return result

    @staticmethod
    async def create(db: AsyncSession, user: Users, data: ProviderCreate) -> ProviderResponse:
        """添加自定义厂商（同用户下名称唯一；与预置厂商同名冲突也拒绝）"""
        if await ProviderRepo.get_by_name(db, user.id, data.name):
            raise HTTPException(status_code=409, detail=f"厂商 {data.name} 已存在")
        # 与预置厂商重名冲突
        preset = (await db.execute(
            select(ModelProviders).where(ModelProviders.name == data.name)
        )).scalars().first()
        if preset is not None:
            raise HTTPException(status_code=409, detail=f"厂商 {data.name} 是预置厂商，无需自定义")

        p = await ProviderRepo.create(
            db, user.id, data.name, data.protocol, data.base_url, data.description)
        await db.commit()
        await db.refresh(p)
        return ProviderResponse(
            id=p.id, name=p.name, protocol=p.protocol, base_url=p.base_url,
            description=p.description, source="custom", model_count=0,
            created_at=p.created_at,
        )

    @staticmethod
    async def update(db: AsyncSession, user: Users, provider_id: UUID, data: ProviderUpdate) -> ProviderResponse:
        """编辑自定义厂商（名称变更时校验唯一）"""
        p = await ProviderRepo.get_by_id(db, provider_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="厂商不存在")

        if data.name is not None and data.name != p.name:
            if await ProviderRepo.get_by_name(db, user.id, data.name):
                raise HTTPException(status_code=409, detail=f"厂商 {data.name} 已存在")
            preset = (await db.execute(
                select(ModelProviders).where(ModelProviders.name == data.name)
            )).scalars().first()
            if preset is not None:
                raise HTTPException(status_code=409, detail=f"厂商 {data.name} 是预置厂商，无法改名为此")

        p = await ProviderRepo.update(
            db, p,
            name=data.name,
            protocol=data.protocol,
            base_url=data.base_url,
            description=data.description,
        )
        await db.commit()
        await db.refresh(p)
        return ProviderResponse(
            id=p.id, name=p.name, protocol=p.protocol, base_url=p.base_url,
            description=p.description, source="custom", model_count=0,
            created_at=p.created_at,
        )

    @staticmethod
    async def delete(db: AsyncSession, user: Users, provider_id: UUID) -> None:
        """删除自定义厂商（不拦截已有配置，provider 字符串解耦）"""
        p = await ProviderRepo.get_by_id(db, provider_id)
        if p is None or p.user_id != user.id:
            raise HTTPException(status_code=404, detail="厂商不存在")
        await ProviderRepo.delete(db, p)
        await db.commit()
