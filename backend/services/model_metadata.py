"""作者：LHF；时间：2026-10-25；作用：从当前模型供应商的模型列表响应发现上下文容量并短期缓存。"""
import hashlib
import time
from collections import OrderedDict

import httpx

_cache = OrderedDict()


def _positive_limit(value):
    """作用：只接受合理的整数 token 容量，拒绝布尔值、小数及无效字段。"""
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        limit = int(value)
    except ValueError:
        return None
    return limit if limit >= 256 else None


def capacity_from_model(row):
    """作用：解析供应商模型对象；不把 max_tokens、usage、生成上限当成上下文容量。"""
    if not isinstance(row, dict):
        return None
    # OpenRouter 的实际提供商限制可能低于模型声明，采用较小的已声明窗口。
    limits = [_positive_limit(row.get(key)) for key in
              ("context_length", "context_window", "max_model_len", "max_input_tokens")]
    top = row.get("top_provider")
    if isinstance(top, dict):
        limits.append(_positive_limit(top.get("context_length")))
    valid = [value for value in limits if value is not None]
    return min(valid) if valid else None


async def fetch_model_capacity(cfg):
    """作用：查询同一 base_url 的 /models；不发送对话正文，不执行模型，失败回退由调用方处理。"""
    base_url = getattr(cfg, "base_url", None)
    if not base_url:
        if str(getattr(cfg, "provider", "")).lower() != "openai":
            return None
        base_url = "https://api.openai.com/v1"
    base_url = base_url.rstrip("/")
    secret = str(getattr(cfg, "api_key", "") or "")
    if not secret:
        return None
    # 缓存隔离端点、模型及凭据；只留摘要，避免不同供应商同名模型串用。
    key = (base_url, cfg.model_name, hashlib.sha256(secret.encode()).hexdigest())
    cached = _cache.get(key)
    if cached and cached[0] > time.monotonic():
        _cache.move_to_end(key)
        return cached[1]
    capacity = None
    try:
        async with httpx.AsyncClient(timeout=3.0, follow_redirects=False) as client:
            response = await client.get(f"{base_url}/models", headers={"Authorization": f"Bearer {secret}"})
            response.raise_for_status()
            payload = response.json()
            rows = payload.get("data", []) if isinstance(payload, dict) else []
            matches = [row for row in rows if isinstance(row, dict) and row.get("id") == cfg.model_name]
            if len(matches) == 1:
                capacity = capacity_from_model(matches[0])
    except (httpx.HTTPError, ValueError, TypeError):
        # 元数据查询不能阻断对话；不输出响应正文、API Key 或含凭据的异常 URL。
        pass
    _cache[key] = (time.monotonic() + (3600 if capacity else 60), capacity)
    _cache.move_to_end(key)
    while len(_cache) > 256:
        _cache.popitem(last=False)
    return capacity
