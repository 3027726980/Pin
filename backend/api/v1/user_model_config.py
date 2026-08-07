"""
用户模型配置 路由

配置体系：
  model_providers（厂商，seed） → default_model_config（默认模型，seed） → user_model_config（用户创建）
  用户创建配置时从 default_model_config 自动带入 base_url/dimension，可手动覆盖
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.models import Users
from backend.schemas.common import SuccessResponse
from backend.models import ModelTypes
from backend.schemas.user_model_config import (
    UserModelConfigCreate,
    UserModelConfigResponse,
    UserModelConfigUpdate,
    DefaultModelConfigResponse,
)
from backend.services import UserModelConfigService

router = APIRouter(prefix="/api/v1/settings/user-model-config", tags=["用户模型配置"])


@router.get(
    "/model-types",
    response_model=SuccessResponse[list[dict]],
    summary="获取模型类型对照表",
)
async def list_model_types(
    db: AsyncSession = Depends(get_db),
):
    from sqlalchemy import select
    q = select(ModelTypes).order_by(ModelTypes.code)
    result = await db.execute(q)
    items = [{"code": m.code, "name": m.name} for m in result.scalars().all()]
    return SuccessResponse(result=items)


@router.get(
    "/defaults",
    response_model=SuccessResponse[list[DefaultModelConfigResponse]],
    summary="获取可选的默认模型列表",
    description="返回所有厂商支持的模型及默认配置，前端展示给用户选择，选中后自动带入 base_url 等参数",
)
async def list_defaults(
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await UserModelConfigService.list_defaults(db)
    return SuccessResponse(result=result)


@router.get(
    "",
    response_model=SuccessResponse[list[UserModelConfigResponse]],
    summary="获取当前用户已创建的模型配置列表",
    description="列出用户所有的模型配置，向量化时从此列表取 active 且 model_type=1 的记录",
)
async def list_user_configs(
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await UserModelConfigService.list_by_user(db, user)
    return SuccessResponse(result=result)


@router.post(
    "",
    response_model=SuccessResponse[UserModelConfigResponse],
    summary="创建新的模型配置",
    description="用户选择厂商模型后创建配置。base_url 填了以用户为准，不填则使用 default_model_config 的默认值。api_key 为必填",
)
async def create_user_config(
    body: UserModelConfigCreate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await UserModelConfigService.create(db, user, body)
    return SuccessResponse(result=result)


@router.put(
    "/{cfg_id}",
    response_model=SuccessResponse[UserModelConfigResponse],
    summary="修改已有的模型配置",
    description="可修改 API Key、接口地址、启用状态等",
)
async def update_user_config(
    cfg_id: UUID,
    body: UserModelConfigUpdate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await UserModelConfigService.update(db, user, cfg_id, body)
    return SuccessResponse(result=result)


@router.delete(
    "/{cfg_id}",
    response_model=SuccessResponse,
    summary="删除指定的模型配置",
    description="删除后向量化将无法使用此配置，请确保有其他 active 的 embedding 配置",
)
async def delete_user_config(
    cfg_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    await UserModelConfigService.delete(db, user, cfg_id)
    return SuccessResponse(message="已删除")
