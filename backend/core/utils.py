"""
通用工具函数

当前提供分页参数解析与 UUID 安全转换，供各路由/服务模块共用。
"""
from uuid import UUID

from backend.core.config import settings


def parse_page(raw: str) -> int:
    """安全解析分页参数：空/非数字 → 默认页码"""
    val = raw.strip() if raw else ""
    if not val:
        return settings.pagination.default_page
    try:
        n = int(val)
        return n if n > 0 else settings.pagination.default_page
    except ValueError:
        return settings.pagination.default_page


def parse_page_size(raw: str) -> int:
    """安全解析每页条数：空/非数字 → 默认值，上限受 max_page_size 约束"""
    val = raw.strip() if raw else ""
    if not val:
        return settings.pagination.default_page_size
    try:
        n = int(val)
        n = n if n > 0 else settings.pagination.default_page_size
        return min(n, settings.pagination.max_page_size)
    except ValueError:
        return settings.pagination.default_page_size


def to_uuid(value) -> UUID:
    """
    UUID 安全转换

    将 str / uuid.UUID / asyncpg.pgproto.UUID（JSONB 读出）统一转 uuid.UUID。
    asyncpg 的 pgproto.UUID 已是 UUID 子类，直接返回；str 则正常解析。
    """
    if isinstance(value, UUID):
        return value
    return UUID(value)
from backend.core.config import settings


def parse_page(raw: str) -> int:
    """安全解析分页参数：空/非数字 → 默认页码"""
    val = raw.strip() if raw else ""
    if not val:
        return settings.pagination.default_page
    try:
        n = int(val)
        return n if n > 0 else settings.pagination.default_page
    except ValueError:
        return settings.pagination.default_page


def parse_page_size(raw: str) -> int:
    """安全解析每页条数：空/非数字 → 默认值，上限受 max_page_size 约束"""
    val = raw.strip() if raw else ""
    if not val:
        return settings.pagination.default_page_size
    try:
        n = int(val)
        n = n if n > 0 else settings.pagination.default_page_size
        return min(n, settings.pagination.max_page_size)
    except ValueError:
        return settings.pagination.default_page_size
