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
import logging
import time
from collections.abc import AsyncIterator

from backend.core.config import settings

logger = logging.getLogger(__name__)
_llm_logger = logging.getLogger("backend.llm")


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
        """
        impl = _resolve_implementation(provider, protocol)
        return await impl.chat(model_name, api_key, base_url, messages, temperature, top_p)

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
    ) -> AsyncIterator[str]:
        """
        流式对话，逐 token 产出回答片段

        与 chat() 参数一致，返回异步生成器
        """
        impl = _resolve_implementation(provider, protocol)
        async for delta in impl.chat_stream(model_name, api_key, base_url, messages, temperature, top_p):
            yield delta


# ── 协议注册表 ─────────────────────────
# 新增协议：实现一个类（chat / chat_stream 静态方法）+ 在此注册一行

class OpenAICompatible:
    """OpenAI 兼容协议实现（DeepSeek / Moonshot / 智谱 / DashScope 等均适用）"""

    protocol = "openai"

    @staticmethod
    def _build_client(api_key: str, base_url: str | None):
        """构建 AsyncOpenAI 客户端（base_url 为空则用官方地址）"""
        from openai import AsyncOpenAI

        return AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or "https://api.openai.com/v1",
            timeout=60.0,
        )

    @staticmethod
    async def chat(
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float,
        top_p: float,
    ) -> str:
        """OpenAI 兼容非流式对话（埋点：耗时 + 输出长度 + 错误）"""
        client = OpenAICompatible._build_client(api_key, base_url)
        t0 = time.perf_counter()
        try:
            resp = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                stream=False,
            )
            content = resp.choices[0].message.content or ""
            _llm_logger.info(
                "model=%s base_url=%s stream=false total_ms=%d chars=%d error=None",
                model_name, base_url or "",
                int((time.perf_counter() - t0) * 1000), len(content))
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
    ) -> AsyncIterator[str]:
        """OpenAI 兼容流式对话（埋点：首 token / 总耗时 / 输出长度 / 错误）"""
        client = OpenAICompatible._build_client(api_key, base_url)
        t0 = time.perf_counter()
        first_token_ms: int | None = None
        chars = 0
        try:
            stream = await client.chat.completions.create(
                model=model_name,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                stream=True,
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


# 协议 → 实现类 注册表
LLM_IMPLEMENTATIONS: dict[str, type] = {
    "openai": OpenAICompatible,
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
    解析调用模式（协议）：显式值优先，其次查 config.yaml 厂商声明，默认 openai
    """
    if protocol:
        return protocol
    providers = getattr(settings, "model_providers", None)
    if providers is not None:
        cfg = getattr(providers, provider, None)
        if cfg is not None and getattr(cfg, "protocol", None):
            return cfg.protocol
    return "openai"
