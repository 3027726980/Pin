"""运行时日志级别管理（管理员）：即时切换 + 可选自动还原

用途：部署后不重启排障——把某个模块临时调到 DEBUG 看细节，expire_minutes 到期自动还原。
还原基准：config.yaml logging.levels（或 logging.level）的初始值。
"""
import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from backend.api.deps import get_current_user
from backend.core.config import settings
from backend.models import Users
from backend.schemas.common import SuccessResponse

router = APIRouter(prefix="/api/v1/debug", tags=["调试"])

# logger 名校验：只允许这些前缀（防乱建 logger）
_ALLOWED_PREFIXES = ("backend.", "sqlalchemy.", "uvicorn")
_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")


def _validate_logger(name: str) -> None:
    if not name.startswith(_ALLOWED_PREFIXES):
        raise HTTPException(
            status_code=422,
            detail=f"logger 名必须以 {'/'.join(_ALLOWED_PREFIXES)} 开头")


class LogLevelBody(BaseModel):
    """切换请求：logger 名 + 级别 + 可选自动还原分钟数"""
    logger: str
    level: str
    expire_minutes: float | None = Field(default=None, ge=0, le=1440)


def _initial_level(logger_name: str) -> str:
    """config.yaml 中该 logger 的初始级别（还原基准）"""
    levels_ns = getattr(settings.logging, "levels", None)
    base = vars(levels_ns) if levels_ns is not None else {}
    return base.get(logger_name, getattr(settings.logging, "level", "INFO"))


@router.get("/log-level", response_model=SuccessResponse[dict], summary="查看日志级别")
async def list_log_levels(user: Users = Depends(get_current_user)):
    """返回已知 logger 的当前级别（管理员）"""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    levels_ns = getattr(settings.logging, "levels", None)
    base = vars(levels_ns) if levels_ns is not None else {}
    result = {}
    for name in base:
        result[name] = logging.getLevelName(logging.getLogger(name).level)
    result["root"] = logging.getLevelName(logging.getLogger().level)
    return SuccessResponse(result=result)


@router.post("/log-level", response_model=SuccessResponse[dict], summary="切换日志级别（可选自动还原）")
async def set_log_level(body: LogLevelBody, user: Users = Depends(get_current_user)):
    """立即切换级别；expire_minutes > 0 时到期自动还原为 config 初始值"""
    if not user.is_superuser:
        raise HTTPException(status_code=403, detail="需要管理员权限")
    _validate_logger(body.logger)
    if body.level not in _LEVELS:
        raise HTTPException(status_code=422, detail=f"级别必须为 {list(_LEVELS)}")

    lgr = logging.getLogger(body.logger)
    lgr.setLevel(getattr(logging, body.level))

    if body.expire_minutes and body.expire_minutes > 0:
        restore = _initial_level(body.logger)

        async def _restore() -> None:
            await asyncio.sleep(body.expire_minutes * 60)
            lgr.setLevel(getattr(logging, restore))
            logging.getLogger("backend").info(
                "日志级别已自动还原: %s → %s", body.logger, restore)

        asyncio.create_task(_restore())

    return SuccessResponse(result={"logger": body.logger, "level": body.level,
                                   "expire_minutes": body.expire_minutes})
