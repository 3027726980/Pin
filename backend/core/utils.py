"""
通用工具函数

当前提供分页参数解析、UUID 安全转换与本地推理设备解析，供各路由/服务模块共用。
"""
import logging
from uuid import UUID

from backend.core.config import settings

logger = logging.getLogger(__name__)


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


def resolve_local_device(configured: str | None, *, what: str = "local model") -> str:
    """
    解析本地模型推理设备（local_models.*.device → 实际 device 字符串）

    规则：
      - cpu：强制 CPU
      - cuda：强制 GPU；环境无 GPU 时 WARNING 降级 CPU（降级不阻断）
      - auto / 空 / None：自动检测（torch.cuda.is_available()，有 GPU 用 cuda）
      - 非法值：WARNING 提示后按 auto 处理
      - 仅支持 cpu / cuda 字面量（cuda:0 / mps 暂不支持），大小写不敏感

    参数:
        configured: 配置的设备值（如 local_models.embedding.device）
        what: 用途标识，用于日志（"embedding" / "rerank"）

    返回: "cpu" 或 "cuda"
    """
    val = (configured or "").strip().lower()
    if val == "cpu":
        return "cpu"

    has_cuda = False
    try:
        import torch  # 延迟导入：仅本地模型推理路径需要
        has_cuda = torch.cuda.is_available()
    except ImportError:
        logger.warning("torch 未安装，%s 本地推理设备按 CPU 处理", what)

    if val == "cuda":
        if has_cuda:
            return "cuda"
        logger.warning(
            "local_models.%s.device=cuda 但未检测到可用 GPU，降级使用 CPU", what)
        return "cpu"

    if val not in ("", "auto"):
        logger.warning(
            "local_models.%s.device 非法值: %r（支持 auto/cpu/cuda），按 auto 处理",
            what, configured)

    return "cuda" if has_cuda else "cpu"
