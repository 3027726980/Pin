"""
Embedding 服务 — 协议注册表模式（provider 名分发，未知厂商默认 OpenAI 兼容）

- aliyun：DashScope 原生 SDK（langchain DashScopeEmbeddings，行为保持）
- openai / 自定义厂商：OpenAI 兼容 API（base_url 可覆盖任意兼容端点）
- local：本地 sentence-transformers（local_files_only）

扩展方式（Phase 4.7，毛毛需求留扩展余地）：
  - 新厂商走 OpenAI 兼容端点 → 零代码（自动默认分支）
  - 其他协议（如厂商专用 SDK）→ 实现一个类（embed 静态方法）+ 注册一行，
    调用方（rag.py / document_process.py）零改动
"""
import logging

from backend.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """统一的 Embedding 入口，按 provider 分发（未知默认 OpenAI 兼容）"""

    @staticmethod
    def embed(provider: str, model_name: str, api_key: str | None, base_url: str | None, texts: list[str], protocol: str | None = None) -> list[list[float]]:
        """
        批量向量化

        参数:
            provider:   厂商名（aliyun / openai / local / 自定义）
            model_name: 模型名
            api_key:    API Key（从 model_config 读取）
            base_url:   API 地址（从 model_config 读取）
            texts:      文本列表（单条传 ["text"]）
            protocol:   调用模式（协议）：模型配置显式选择时优先；空 = 按厂商名推断
                        （aliyun→dashscope / local→local / 其他→openai）

        返回: 向量列表，与 texts 一一对应
        """
        proto = protocol or _PROTOCOL_BY_PROVIDER.get(provider, "openai")
        impl = EMBEDDING_IMPLEMENTATIONS.get(proto, OpenAICompatibleEmbedding)
        return impl.embed(model_name, api_key, base_url, texts)


class DashScopeEmbedding:
    """阿里云 DashScope Embedding（原生 SDK 链路）"""

    @staticmethod
    def embed(model_name: str, api_key: str | None, base_url: str | None, texts: list[str]) -> list[list[float]]:
        from langchain_community.embeddings import DashScopeEmbeddings

        embedding_model = DashScopeEmbeddings(
            model=model_name,
            dashscope_api_key=api_key,
        )
        return embedding_model.embed_documents(texts)


class OpenAICompatibleEmbedding:
    """OpenAI 兼容 Embedding（自定义厂商默认实现，base_url 可覆盖任意兼容端点）"""

    @staticmethod
    def embed(model_name: str, api_key: str | None, base_url: str | None, texts: list[str]) -> list[list[float]]:
        from openai import OpenAI

        client = OpenAI(api_key=api_key or "", base_url=base_url or None)
        resp = client.embeddings.create(model=model_name, input=texts)
        return [d.embedding for d in resp.data]


class LocalEmbedding:
    """本地 Embedding，仅从本地加载，不联网下载"""

    @staticmethod
    def embed(model_name: str, api_key: str | None, base_url: str | None, texts: list[str]) -> list[list[float]]:
        from pathlib import Path

        from sentence_transformers import SentenceTransformer

        from backend.core.config import settings

        # 本地模型目录（local_models 顶层配置） / 模型名 → 本地路径
        model_dir = Path(settings.local_models.cache_dir) / model_name
        if not model_dir.exists():
            raise FileNotFoundError(
                f"本地模型不存在: {model_dir}，请先下载模型到该目录"
            )

        model = SentenceTransformer(
            str(model_dir),
            device="cpu",
            local_files_only=True,
        )
        results = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return results.tolist()


# 厂商名 → 默认调用模式（Embedding 用；模型配置显式选择时优先于此处）
_PROTOCOL_BY_PROVIDER: dict[str, str] = {
    "aliyun": "dashscope",
    "local": "local",
    "openai": "openai",
}

# 调用模式 → 实现类 注册表（未知回退 OpenAI 兼容）
EMBEDDING_IMPLEMENTATIONS: dict[str, type] = {
    "openai": OpenAICompatibleEmbedding,
    "dashscope": DashScopeEmbedding,
    "local": LocalEmbedding,
}
