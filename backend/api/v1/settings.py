"""系统设置管理接口（管理员）：列表 / 详情 / 更新（更新后立即生效）"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from backend.api.deps import get_current_user
from backend.core.database import get_db
from backend.models import Users
from backend.services.system_settings import SystemSettingsService

router = APIRouter(prefix="/api/v1/settings", tags=["系统设置"])


class SettingBody(BaseModel):
    """设置更新请求体：value 为任意 JSON"""
    value: dict


@router.get("", summary="设置列表")
async def list_settings(
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """全部设置项（含描述与更新时间），管理员"""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return {"result": await SystemSettingsService.get_all(db)}


@router.get("/{key}", summary="设置详情")
async def get_setting(
    key: str,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """单项设置（缓存读取），管理员"""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    value = SystemSettingsService.get(key)
    if value is None:
        raise HTTPException(status_code=404, detail="设置项不存在")
    return {"result": {"key": key, "value": value}}


@router.put("/{key}", summary="更新设置（立即生效）")
async def update_setting(
    key: str,
    body: SettingBody,
    db: AsyncSession = Depends(get_db),
    user: Users = Depends(get_current_user),
):
    """更新设置值：写库 → 刷新缓存 → 触发变更回调（如脱敏 Filter 重建），管理员"""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return {"result": await SystemSettingsService.update(db, key, body.value)}
