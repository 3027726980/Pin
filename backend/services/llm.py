"""
LLM 服务 — Provider 模式

通过 switch 匹配不同厂商，方便后续扩展。
MVP 仅支持 openai（OpenAI 兼容协议，base_url 可覆盖为任意兼容厂商）。
"""
import logging
from collections.abc import AsyncIterator
from openai import AsyncOpenAI
logger = logging.getLogger(__name__)


class LLMService:
    """统一的 LLM 调用入口，按 provider 分发"""

    @staticmethod
    async def chat(
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> str:
        """
        非流式对话，返回完整回答文本

        参数:
            provider:   厂商名（MVP 仅支持 openai）
            model_name: 模型名
            api_key:    API Key
            base_url:   API 地址（可覆盖为任意 OpenAI 兼容厂商）
            messages:   [{role, content}, ...]
            temperature / top_p: 采样参数
        """
        if provider == "openai":
            return await _chat_openai(model_name, api_key, base_url, messages, temperature, top_p)
        raise ValueError(f"暂不支持的 LLM Provider: {provider}")

    @staticmethod
    async def chat_stream(
        provider: str,
        model_name: str,
        api_key: str,
        base_url: str | None,
        messages: list[dict],
        temperature: float = 0.7,
        top_p: float = 0.9,
    ) -> AsyncIterator[str]:
        """
        流式对话，逐 token 产出回答片段

        与 chat() 参数一致，返回异步生成器
        """
        if provider == "openai":
            async for delta in _chat_openai_stream(model_name, api_key, base_url, messages, temperature, top_p):
                yield delta
            return
        raise ValueError(f"暂不支持的 LLM Provider: {provider}")


# ── OpenAI 兼容实现 ─────────────────────

def _build_client(api_key: str, base_url: str | None):
    """构建 AsyncOpenAI 客户端（base_url 为空则用官方地址）"""


    return AsyncOpenAI(
        api_key=api_key,
        base_url=base_url or "https://api.openai.com/v1",
        timeout=60.0,
    )


async def _chat_openai(
    model_name: str,
    api_key: str,
    base_url: str | None,
    messages: list[dict],
    temperature: float,
    top_p: float,
) -> str:
    """OpenAI 兼容非流式对话"""
    client = _build_client(api_key, base_url)
    resp = await client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        stream=False,
    )
    return resp.choices[0].message.content or ""


async def _chat_openai_stream(
    model_name: str,
    api_key: str,
    base_url: str | None,
    messages: list[dict],
    temperature: float,
    top_p: float,
) -> AsyncIterator[str]:
    """OpenAI 兼容流式对话，逐 chunk 提取 delta.content"""
    client = _build_client(api_key, base_url)
    stream = await client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=temperature,
        top_p=top_p,
        stream=True,
    )
    async for chunk in stream:
        if chunk.choices and chunk.choices[0].delta.content:
            yield chunk.choices[0].delta.content
