"""
模型配置 路由
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.models import User
from backend.schemas.common import SuccessResponse
from backend.schemas.model_config import (
    ModelConfigCreate,
    ModelConfigResponse,
    ModelConfigUpdate,
)
from backend.services import ModelConfigService

router = APIRouter(prefix="/api/v1/settings/model-config", tags=["模型配置"])


@router.get("", response_model=SuccessResponse[list[ModelConfigResponse]], summary="模型配置列表")
async def list_configs(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await ModelConfigService.list_by_user(db, user)
    return SuccessResponse(result=result)


@router.post("", response_model=SuccessResponse[ModelConfigResponse], summary="新增模型配置")
async def create_config(
    body: ModelConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await ModelConfigService.create(db, user, body)
    return SuccessResponse(result=result)


@router.put("/{cfg_id}", response_model=SuccessResponse[ModelConfigResponse], summary="编辑模型配置")
async def update_config(
    cfg_id: UUID,
    body: ModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    result = await ModelConfigService.update(db, user, cfg_id, body)
    return SuccessResponse(result=result)


@router.delete("/{cfg_id}", response_model=SuccessResponse, summary="删除模型配置")
async def delete_config(
    cfg_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User = Depends(get_current_user),
):
    await ModelConfigService.delete(db, user, cfg_id)
    return SuccessResponse(message="已删除")
