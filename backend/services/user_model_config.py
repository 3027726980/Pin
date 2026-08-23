"""
用户模型配置 业务逻辑
"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import (
    GeneralAgentRepo,
    KnowledgeBaseRepo,
    SimpleRagAgentRepo,
    UserModelConfigRepo,
)
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
        await UserModelConfigService._ensure_base_url(db, data.provider, data.base_url)
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
    async def _find_references(db: AsyncSession, cfg_id: UUID) -> tuple[list, list]:
        """
        查找引用该模型配置的知识库与 Agent（均未删除）

        返回 (kbs, agents)
        """
        kbs = await KnowledgeBaseRepo.find_by_model_config(db, cfg_id)
        agents = await GeneralAgentRepo.find_by_model_config(db, cfg_id)
        agents += await SimpleRagAgentRepo.find_by_model_config(db, cfg_id)
        return kbs, agents

    @staticmethod
    def _ref_error(kbs: list, agents: list) -> HTTPException:
        """组装引用冲突错误（409）"""
        parts = []
        if kbs:
            names = "、".join(kb.name for kb in kbs[:3])
            parts.append(f"{len(kbs)} 个知识库（{names}）")
        if agents:
            names = "、".join(a.name for a in agents[:3])
            parts.append(f"{len(agents)} 个 Agent（{names}）")
        return HTTPException(
            status_code=409,
            detail=f"该模型配置正被{'、'.join(parts)}引用，请先解除绑定后再操作",
        )

    @staticmethod
    async def _ensure_base_url(db: AsyncSession, provider: str, base_url: str | None) -> None:
        """
        自定义厂商（不在预置列表）必须填写接口地址

        预置厂商（config.yaml seed 的 default_model_config）有默认地址可推断，base_url 可空；
        自定义厂商无默认地址，不填会导致调用失败。
        """
        if base_url:
            return
        if await UserModelConfigRepo.exists_provider(db, provider):
            return
        raise HTTPException(status_code=400, detail="自定义厂商必须填写接口地址")

    @staticmethod
    async def update(db: AsyncSession, user: Users, cfg_id: UUID, data: UserModelConfigUpdate) -> UserModelConfigResponse:
        cfg = await UserModelConfigRepo.get_by_id(db, cfg_id)
        if cfg is None or cfg.user_id != user.id:
            raise HTTPException(status_code=404, detail="配置不存在")

        # 仅当厂商变更时校验新厂商的 base_url（未变不重复校验）
        if data.provider is not None and data.provider != cfg.provider:
            await UserModelConfigService._ensure_base_url(db, data.provider, data.base_url)

        # 禁用前检查引用（知识库 + 两类 Agent）
        if data.is_active is False and cfg.is_active:
            kbs, agents = await UserModelConfigService._find_references(db, cfg_id)
            if kbs or agents:
                raise UserModelConfigService._ref_error(kbs, agents)

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

        # 删除前检查引用（知识库 + 两类 Agent），避免外键冲突 500
        kbs, agents = await UserModelConfigService._find_references(db, cfg_id)
        if kbs or agents:
            raise UserModelConfigService._ref_error(kbs, agents)

        await UserModelConfigRepo.delete(db, cfg)
        await db.commit()
