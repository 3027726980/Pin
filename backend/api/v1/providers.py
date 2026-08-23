"""
用户自定义厂商 路由
"""
from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.models import Users
from backend.schemas.common import SuccessResponse
from backend.schemas.providers import ProviderCreate, ProviderResponse, ProviderUpdate
from backend.services import ProviderService

router = APIRouter(prefix="/api/v1/settings/providers", tags=["厂商管理"])


@router.get(
    "",
    response_model=SuccessResponse[list[ProviderResponse]],
    summary="厂商合并列表（预置 + 自定义）",
    description="预置厂商来自 config.yaml（启动 seed）；自定义厂商来自 user_providers 表",
)
async def list_providers(
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await ProviderService.list_all(db, user)
    return SuccessResponse(result=result)


@router.post(
    "",
    response_model=SuccessResponse[ProviderResponse],
    summary="添加自定义厂商",
    description="效果等同 config.yaml 预置厂商（带调用模式），添加后即可在模型配置中选择",
)
async def create_provider(
    body: ProviderCreate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await ProviderService.create(db, user, body)
    return SuccessResponse(result=result)


@router.put(
    "/{provider_id}",
    response_model=SuccessResponse[ProviderResponse],
    summary="编辑自定义厂商",
)
async def update_provider(
    provider_id: UUID,
    body: ProviderUpdate,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    result = await ProviderService.update(db, user, provider_id, body)
    return SuccessResponse(result=result)


@router.delete(
    "/{provider_id}",
    response_model=SuccessResponse,
    summary="删除自定义厂商",
    description="不拦截已有模型配置（厂商为字符串解耦），删除后仅不可新建该厂商配置",
)
async def delete_provider(
    provider_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    await ProviderService.delete(db, user, provider_id)
    return SuccessResponse(message="已删除")
