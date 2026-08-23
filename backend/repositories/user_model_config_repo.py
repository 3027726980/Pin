"""
用户模型配置 数据访问
"""
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import UserModelConfig, DefaultModelConfig


class UserModelConfigRepo:
    """用户模型配置 CRUD"""

    @staticmethod
    async def create(
        db: AsyncSession,
        user_id: UUID,
        provider: str,
        model_name: str,
        model_type: int,
        base_url: str | None,
        api_key: str | None,
        dimension: int | None,
        protocol: str | None = None,
        temperature: float | None = None,
        top_p: float | None = None,
        max_tokens: int | None = None,
        is_active: bool = True,
    ) -> UserModelConfig:
        cfg = UserModelConfig(
            user_id=user_id,
            provider=provider,
            model_name=model_name,
            model_type=model_type,
            base_url=base_url,
            api_key=api_key,
            dimension=dimension,
            protocol=protocol,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
            is_active=is_active,
        )
        db.add(cfg)
        await db.flush()
        return cfg

    @staticmethod
    async def get_by_id(db: AsyncSession, cfg_id: UUID) -> UserModelConfig | None:
        return await db.get(UserModelConfig, cfg_id)

    @staticmethod
    async def list_by_user(db: AsyncSession, user_id: UUID) -> list[UserModelConfig]:
        q = (
            select(UserModelConfig)
            .where(UserModelConfig.user_id == user_id)
            .order_by(UserModelConfig.model_type, UserModelConfig.created_at.desc())
        )
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def update(db: AsyncSession, cfg: UserModelConfig, **kwargs) -> UserModelConfig:
        for key, value in kwargs.items():
            if value is not None:
                setattr(cfg, key, value)
        await db.flush()
        return cfg

    @staticmethod
    async def delete(db: AsyncSession, cfg: UserModelConfig) -> None:
        await db.delete(cfg)
        await db.flush()

    @staticmethod
    async def find_active_embedding(
        db: AsyncSession, user_id: UUID
    ) -> UserModelConfig | DefaultModelConfig | None:
        """
        找启用的 embedding 配置
        优先查 user_model_config（用户创建的），没有则取 default_model_config 第一条
        """
        # 先查用户配置
        q = (
            select(UserModelConfig)
            .where(
                UserModelConfig.user_id == user_id,
                UserModelConfig.model_type == 1,
                UserModelConfig.is_active == True,
            )
        )
        result = await db.execute(q)
        cfg = result.scalars().first()
        if cfg is not None:
            return cfg

        # 回落默认配置
        q = select(DefaultModelConfig).where(
            DefaultModelConfig.model_type == 1
        ).limit(1)
        result = await db.execute(q)
        return result.scalars().first()

    @staticmethod
    async def list_default_configs(db: AsyncSession) -> list[DefaultModelConfig]:
        q = select(DefaultModelConfig).order_by(DefaultModelConfig.provider, DefaultModelConfig.model_name)
        result = await db.execute(q)
        return list(result.scalars().all())

    @staticmethod
    async def exists_provider(db: AsyncSession, provider: str) -> bool:
        """
        判断厂商是否为预置厂商（存在于 default_model_config 表，即 config.yaml seed）

        用于创建/编辑校验：预置厂商 base_url 可空（走默认地址）；自定义厂商必须填接口地址
        """
        q = select(DefaultModelConfig.id).where(
            DefaultModelConfig.provider == provider
        ).limit(1)
        result = await db.execute(q)
        return result.scalars().first() is not None
