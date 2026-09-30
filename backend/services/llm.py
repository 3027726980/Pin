"""
LLM 服务 — 协议注册表模式

按「协议」分发，而非按「厂商名」：
  - config.yaml 的 model_providers 下每个厂商声明 protocol（如 openai）
  - 同一协议的所有厂商共享一个实现（OpenAI 兼容协议 = 一个实现，base_url 区分厂商）
  - 新增 OpenAI 兼容厂商：config.yaml 加 protocol: openai + models 即可，**零代码改动**
  - 新增协议：注册一个新实现类到 LLM_IMPLEMENTATIONS

协议解析：查 config.yaml providers[provider].protocol，查不到默认 "openai"
（OpenAI 兼容是事实标准，即使厂商从配置删除，已有数据也能继续工作）。
"""
import hashlib
import logging
import time
from collections.abc import AsyncIterator
from dataclasses import dataclass

from backend.core.config import settings
from backend.core.observability.context import current_trace
from backend.services.model_policy import (
    current_turn_budget,
    model_requests_per_minute,
    normalize_sampling_params,
)

logger = logging.getLogger(__name__)
_llm_logger = logging.getLogger("backend.llm")
_llm_metrics_logger = logging.getLogger("backend.llm.metrics")


@dataclass(slots=True)
class LLMCallMetrics:
    """一次直接 LLM 调用的排队、首 Token 和总耗时。"""

    queue_wait_ms: int = 0
    first_token_ms: int | None = None
    generation_ms: int | None = None
    total_ms: int = 0
    chars: int = 0
    attempt: int = 1


_LANGCHAIN_RATE_LIMITERS: dict[str, object] = {}
_OPENAI_CLIENTS: dict[tuple[str, str, float], object] = {}


async def close_llm_clients() -> None:
    """应用退出时关闭所有缓存的异步客户端。"""
    clients = list(_OPENAI_CLIENTS.values())
    _OPENAI_CLIENTS.clear()
    for client in clients:
        close = getattr(client, "close", None)
        if close is not None:
            result = close()
            if hasattr(result, "__await__"):
                await result


def get_rate_limiter(provider: str, model_name: str, api_key: str):
    """返回按供应商/API Key 共享的 LangChain 限流器，未知配额返回 None。"""
    rpm = model_requests_per_minute(provider, model_name)
    if not rpm:
        return None
    from langchain_core.rate_limiters import InMemoryRateLimiter

    identity = hashlib.sha256(api_key.encode("utf-8")).hexdigest()[:16]
    key = f"{provider.lower()}:{identity}"
    if key not in _LANGCHAIN_RATE_LIMITERS:
        limiter = InMemoryRateLimiter(
            requests_per_second=rpm / 60,
            check_every_n_seconds=0.1,
            max_bucket_size=1,
        )
        limiter.available_tokens = 1.0
        _LANGCHAIN_RATE_LIMITERS[key] = limiter
    return _LANGCHAIN_RATE_LIMITERS[key]


async def _acquire_request_slot(provider: str, model_name: str, api_key: str) -> None:
    limiter = get_rate_limiter(provider, model_name, api_key)
    if limiter is not None:
        await limiter.aacquire()


def _log_llm_metric(event: str, **payload: object) -> None:
    """写入不含 Prompt、回答和 API Key 的结构化模型指标。"""
    trace = current_trace()
    structured = {
        "event": event,
        "request_id": trace.request_id if trace else None,
        "trace_id": trace.trace_id if trace else None,
        "turn_id": trace.turn_id if trace else None,
        **payload,
    }
    level = logging.ERROR if event == "llm.failed" else logging.INFO
    _llm_metrics_logger.log(
        level, event, extra={"structured_data": structured}
    )


class LLMService:
    """统一的 LLM 调用入口，按协议分发"""

    @staticmethod
    async def chat(
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float = 0.7,
        top_p: float = 0.9,
        protocol: str | None = None,
        timeout: float = 60.0,
        max_tokens: int | None = None,
        purpose: str = "answer",
        metrics: LLMCallMetrics | None = None,
    ) -> str:
        """
        非流式对话，返回完整回答文本

        参数:
            provider:   厂商名（用于解析协议，如 openai / deepseek / aliyun）
            model_name: 模型名
            api_key:    API Key
            base_url:   API 地址（可覆盖为任意 OpenAI 兼容厂商）
            messages:   [{role, content}, ...]
            temperature / top_p: 采样参数
            protocol:   显式调用模式（协议），优先于厂商推断；空 = 查 config.yaml 默认 openai
            timeout:    请求超时秒数（默认 60；配置测试场景传短超时快速失败）
            max_tokens: 最大生成 token 数（空 = 厂商默认）
        """
        impl = _resolve_implementation(provider, protocol)
        call_metrics = metrics or LLMCallMetrics()
        temperature, top_p = normalize_sampling_params(
            provider, model_name, temperature, top_p)
        _log_llm_metric(
            "llm.started", purpose=purpose, provider=provider,
            model=model_name, stream=False, attempt=call_metrics.attempt,
        )
        total_started = time.perf_counter()
        queue_started = time.perf_counter()
        try:
            budget = current_turn_budget()
            if budget is not None:
                budget.acquire_llm()
            await _acquire_request_slot(provider, model_name, api_key)
            call_metrics.queue_wait_ms = round(
                (time.perf_counter() - queue_started) * 1000
            )
            generation_started = time.perf_counter()
            content = await impl.chat(
                model_name, api_key, base_url, messages, temperature, top_p,
                timeout, max_tokens,
            )
            call_metrics.generation_ms = round(
                (time.perf_counter() - generation_started) * 1000
            )
            call_metrics.total_ms = max(
                round((time.perf_counter() - total_started) * 1000),
                call_metrics.queue_wait_ms + call_metrics.generation_ms,
            )
            call_metrics.chars = len(content)
            _log_llm_metric(
                "llm.completed", purpose=purpose, provider=provider,
                model=model_name, stream=False, status="completed",
                queue_wait_ms=call_metrics.queue_wait_ms,
                first_token_ms=None,
                generation_ms=call_metrics.generation_ms,
                total_ms=call_metrics.total_ms,
                chars=call_metrics.chars,
                attempt=call_metrics.attempt,
            )
            return content
        except Exception as error:
            call_metrics.total_ms = round(
                (time.perf_counter() - total_started) * 1000
            )
            _log_llm_metric(
                "llm.failed", purpose=purpose, provider=provider,
                model=model_name, stream=False, status="failed",
                queue_wait_ms=call_metrics.queue_wait_ms,
                total_ms=call_metrics.total_ms,
                attempt=call_metrics.attempt,
                error_type=error.__class__.__name__,
            )
            raise

    @staticmethod
    async def chat_stream(
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float = 0.7,
        top_p: float = 0.9,
        protocol: str | None = None,
        timeout: float = 60.0,
        max_tokens: int | None = None,
        purpose: str = "answer",
        metrics: LLMCallMetrics | None = None,
    ) -> AsyncIterator[str]:
        """
        流式对话，逐 token 产出回答片段

        与 chat() 参数一致，返回异步生成器
        """
        impl = _resolve_implementation(provider, protocol)
        call_metrics = metrics or LLMCallMetrics()
        temperature, top_p = normalize_sampling_params(
            provider, model_name, temperature, top_p)
        _log_llm_metric(
            "llm.started", purpose=purpose, provider=provider,
            model=model_name, stream=True, attempt=call_metrics.attempt,
        )
        total_started = time.perf_counter()
        queue_started = time.perf_counter()
        try:
            budget = current_turn_budget()
            if budget is not None:
                budget.acquire_llm()
            await _acquire_request_slot(provider, model_name, api_key)
            call_metrics.queue_wait_ms = round(
                (time.perf_counter() - queue_started) * 1000
            )
            generation_started = time.perf_counter()
            async for delta in impl.chat_stream(
                model_name, api_key, base_url, messages, temperature, top_p,
                timeout, max_tokens,
            ):
                if call_metrics.first_token_ms is None:
                    call_metrics.first_token_ms = round(
                        (time.perf_counter() - generation_started) * 1000
                    )
                call_metrics.chars += len(delta)
                yield delta
            call_metrics.generation_ms = round(
                (time.perf_counter() - generation_started) * 1000
            )
            call_metrics.total_ms = max(
                round((time.perf_counter() - total_started) * 1000),
                call_metrics.queue_wait_ms + call_metrics.generation_ms,
            )
            _log_llm_metric(
                "llm.completed", purpose=purpose, provider=provider,
                model=model_name, stream=True, status="completed",
                queue_wait_ms=call_metrics.queue_wait_ms,
                first_token_ms=call_metrics.first_token_ms,
                generation_ms=call_metrics.generation_ms,
                total_ms=call_metrics.total_ms,
                chars=call_metrics.chars,
                attempt=call_metrics.attempt,
            )
        except Exception as error:
            call_metrics.total_ms = round(
                (time.perf_counter() - total_started) * 1000
            )
            _log_llm_metric(
                "llm.failed", purpose=purpose, provider=provider,
                model=model_name, stream=True, status="failed",
                queue_wait_ms=call_metrics.queue_wait_ms,
                first_token_ms=call_metrics.first_token_ms,
                total_ms=call_metrics.total_ms,
                attempt=call_metrics.attempt,
                error_type=error.__class__.__name__,
            )
            raise


# ── 协议注册表 ─────────────────────────
# 新增协议：实现一个类（chat / chat_stream 静态方法）+ 在此注册一行

class OpenAICompatible:
    """OpenAI 兼容协议实现（DeepSeek / Moonshot / 智谱 / DashScope 等均适用）"""

    protocol = "openai"

    @staticmethod
    def _build_client(api_key: str, base_url: str | None, timeout: float = 60.0):
        """按连接参数复用 AsyncOpenAI 客户端，避免每次请求重建连接池。"""
        from openai import AsyncOpenAI

        identity = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        key = (identity, base_url or "https://api.openai.com/v1", float(timeout))
        if key not in _OPENAI_CLIENTS:
            _OPENAI_CLIENTS[key] = AsyncOpenAI(
                api_key=api_key,
                base_url=key[1],
                timeout=timeout,
                max_retries=0,
            )
        return _OPENAI_CLIENTS[key]

    @staticmethod
    async def chat(
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float,
        top_p: float,
        timeout: float = 60.0,
        max_tokens: int | None = None,
    ) -> str:
        """OpenAI 兼容非流式对话（埋点：耗时 + 输出长度 + 错误）"""
        client = OpenAICompatible._build_client(api_key, base_url, timeout)
        t0 = time.perf_counter()
        try:
            kwargs = {}
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            resp = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                stream=False,
                **kwargs,
            )
            content = resp.choices[0].message.content or ""
            usage = getattr(resp, "usage", None)
            _llm_logger.info(
                "model=%s base_url=%s stream=false total_ms=%d chars=%d "
                "prompt_tokens=%s completion_tokens=%s error=None",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), len(content),
                getattr(usage, "prompt_tokens", None) if usage else None,
                getattr(usage, "completion_tokens", None) if usage else None)
            return content
        except Exception as e:
            _llm_logger.error(
                "model=%s base_url=%s stream=false total_ms=%d error=%s",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), e)
            raise

    @staticmethod
    async def chat_stream(
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float,
        top_p: float,
        timeout: float = 60.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """OpenAI 兼容流式对话（埋点：首 token / 总耗时 / 输出长度 / 错误）"""
        client = OpenAICompatible._build_client(api_key, base_url, timeout)
        t0 = time.perf_counter()
        first_token_ms: int | None = None
        chars = 0
        try:
            kwargs = {}
            if max_tokens:
                kwargs["max_tokens"] = max_tokens
            stream = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                stream=True,
                **kwargs,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta.content:
                    if first_token_ms is None:
                        first_token_ms = int((time.perf_counter() - t0) * 1000)
                    chars += len(chunk.choices[0].delta.content)
                    yield chunk.choices[0].delta.content
            _llm_logger.info(
                "model=%s base_url=%s stream=true first_token_ms=%s total_ms=%d chars=%d error=None",
                model_name, base_url or "", first_token_ms,
                int((time.perf_counter() - t0) * 1000), chars)
        except Exception as e:
            _llm_logger.error(
                "model=%s base_url=%s stream=true total_ms=%d error=%s",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), e)
            raise


class DashScopeLLM:
    """阿里云百炼 DashScope 原生 LLM（非 OpenAI 兼容；/api/v1/services/aigc/text-generation/generation）"""

    protocol = "dashscope"

    @staticmethod
    async def chat(
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float,
        top_p: float,
        timeout: float = 60.0,
        max_tokens: int | None = None,
    ) -> str:
        """DashScope 原生非流式对话（埋点：耗时 + 输出长度 + 错误）"""
        import httpx

        url = (base_url or "https://dashscope.aliyuncs.com/api/v1").rstrip("/") \
            + "/services/aigc/text-generation/generation"
        params = {"temperature": temperature, "top_p": top_p}
        if max_tokens:
            params["max_tokens"] = max_tokens
        body = {"model": model_name, "input": {"messages": messages}, "parameters": params}
        t0 = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(
                    url, json=body,
                    headers={"Authorization": f"Bearer {api_key}"})
                resp.raise_for_status()
                data = resp.json()
            content = (data.get("output") or {}).get("text") or ""
            usage = data.get("usage") or {}
            _llm_logger.info(
                "model=%s base_url=%s stream=false total_ms=%d chars=%d "
                "prompt_tokens=%s completion_tokens=%s error=None",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), len(content),
                usage.get("input_tokens"), usage.get("output_tokens"))
            return content
        except Exception as e:
            _llm_logger.error(
                "model=%s base_url=%s stream=false total_ms=%d error=%s",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), e)
            raise

    @staticmethod
    async def chat_stream(
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float,
        top_p: float,
        timeout: float = 60.0,
        max_tokens: int | None = None,
    ) -> AsyncIterator[str]:
        """DashScope 原生流式对话（incremental_output SSE）"""
        import httpx

        url = (base_url or "https://dashscope.aliyuncs.com/api/v1").rstrip("/") \
            + "/services/aigc/text-generation/generation"
        params = {"temperature": temperature, "top_p": top_p, "incremental_output": True}
        if max_tokens:
            params["max_tokens"] = max_tokens
        body = {"model": model_name, "input": {"messages": messages}, "parameters": params}
        t0 = time.perf_counter()
        chars = 0
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                        "POST", url, json=body,
                        headers={"Authorization": f"Bearer {api_key}"}) as resp:
                    resp.raise_for_status()
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        import json
                        try:
                            data = json.loads(line[5:].strip())
                        except Exception:
                            continue
                        text = (data.get("output") or {}).get("text") or ""
                        if text:
                            chars += len(text)
                            yield text
            _llm_logger.info(
                "model=%s base_url=%s stream=true total_ms=%d chars=%d error=None",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), chars)
        except Exception as e:
            _llm_logger.error(
                "model=%s base_url=%s stream=true total_ms=%d error=%s",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), e)
            raise


# 协议 → 实现类 注册表
LLM_IMPLEMENTATIONS: dict[str, type] = {
    "openai": OpenAICompatible,
    "dashscope": DashScopeLLM,
}


# ── 内部工具 ─────────────────────────────

def _resolve_implementation(provider: str, protocol: str | None = None) -> type:
    """
    按调用模式解析实现

    解析链：显式 protocol（配置声明的调用模式）→ config.yaml providers[provider].protocol
    → 默认 openai 兼容实现（事实标准，容错）
    协议明确但实现未注册 → 抛错（需要注册新实现）
    """
    resolved = _resolve_protocol(provider, protocol)
    impl = LLM_IMPLEMENTATIONS.get(resolved)
    if impl is None:
        raise ValueError(
            f"协议 {resolved!r}（provider={provider}）未注册实现，"
            f"请实现并注册到 LLM_IMPLEMENTATIONS"
        )
    return impl


def _resolve_protocol(provider: str, protocol: str | None = None) -> str:
    """
    解析调用模式（协议）：显式值优先，其次查 config.yaml preset_providers 声明，默认 openai
    """
    if protocol:
        return protocol
    preset = getattr(settings, "preset_providers", None) or []
    for p in preset:
        if p["name"] == provider:
            return p.get("protocol") or "openai"
    return "openai"
