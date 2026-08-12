"""系统设置业务：读写 + 内存缓存 + config.yaml 默认值 seed

- 事实来源：数据库 system_settings（启动加载入内存缓存，日志等高频路径不查库）
- 默认值：config.yaml（首次 seed，key 不存在时写入）
- 修改后：刷新缓存 + 触发 on_change 回调（如重建日志脱敏 Filter），立即生效
- 解析：JSONB → dict，后端自行解析，不引第三方配置库
"""
from typing import Any, Awaitable, Callable

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.repositories import SystemSettingsRepo

# 默认值定义（新设置项在此注册；首次启动 seed 入数据库）
DEFAULT_SETTINGS: dict[str, dict] = {
    "logging.redact_rules": {
        "enabled": bool(getattr(getattr(settings, "logging", None),
                                "redact_sensitive", True)),
        "rules": [
            {"type": "field_name", "pattern": "api_key|token|password|secret|authorization",
             "mask": "keep_4_4"},
            {"type": "value_pattern", "pattern": r"sk-[A-Za-z0-9]+", "mask": "keep_4_4"},
            {"type": "value_pattern", "pattern": r"pin_[A-Za-z0-9]+", "mask": "keep_4_4"},
        ],
    },
}

# 内存缓存（进程内；多 worker 部署时各自缓存，可接受）
_cache: dict[str, dict] = {}
_on_change: list[Callable[[str, dict], Awaitable[None]]] = []


class SystemSettingsService:
    """系统设置读写（内存缓存 + 变更回调）"""

    @staticmethod
    def register_on_change(cb: Callable[[str, dict], Awaitable[None]]) -> None:
        """注册变更回调（key 更新后调用，如日志 Filter 重建）"""
        _on_change.append(cb)

    @staticmethod
    async def init(db: AsyncSession) -> None:
        """启动初始化：seed 默认值（key 不存在时）+ 加载缓存"""
        for key, default in DEFAULT_SETTINGS.items():
            row = await SystemSettingsRepo.get_by_key(db, key)
            if row is None:
                await SystemSettingsRepo.upsert(db, key, default)
                await db.commit()
        _cache.clear()
        for row in await SystemSettingsRepo.list_all(db):
            _cache[row.key] = row.value

    @staticmethod
    def get(key: str) -> dict | None:
        """读缓存（同步，日志等高频路径用）"""
        return _cache.get(key)

    @staticmethod
    async def get_all(db: AsyncSession) -> list[dict]:
        """设置列表（含描述）"""
        rows = await SystemSettingsRepo.list_all(db)
        return [{"key": r.key, "value": r.value, "description": r.description,
                 "updated_at": r.updated_at.isoformat()} for r in rows]

    @staticmethod
    async def update(db: AsyncSession, key: str, value: dict) -> dict:
        """更新设置：写库 → 刷新缓存 → 触发变更回调（立即生效）"""
        if key not in _cache:
            raise HTTPException(status_code=404, detail=f"设置项不存在: {key}")
        await SystemSettingsRepo.upsert(db, key, value)
        await db.commit()
        _cache[key] = value
        for cb in _on_change:
            await cb(key, value)
        return value
