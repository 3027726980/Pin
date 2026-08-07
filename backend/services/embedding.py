"""
Embedding 服务 — Provider 模式

通过 switch 匹配不同厂商，方便后续扩展。
MVP 仅支持 aliyun（DashScope）。
"""
import logging

from backend.core.config import settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """统一的 Embedding 入口，按 provider 分发"""

    @staticmethod
    def embed(provider: str, model_name: str, api_key: str | None, base_url: str | None, texts: list[str]) -> list[list[float]]:
        """
        批量向量化

        参数:
            provider:   厂商名（aliyun / openai / ...）
            model_name: 模型名
            api_key:    API Key（从 model_config 读取）
            base_url:   API 地址（从 model_config 读取）
            texts:      文本列表（单条传 ["text"]）

        返回: 向量列表，与 texts 一一对应
        """
        if provider == "aliyun":
            return _embed_aliyun(model_name, api_key, texts)
        elif provider == "openai":
            return _embed_openai(model_name, api_key, texts)
        elif provider == "local":
            return _embed_local(model_name, texts)
        else:
            raise ValueError(f"不支持的 Embedding Provider: {provider}")


def _embed_aliyun(model_name: str, api_key: str | None, texts: list[str]) -> list[list[float]]:
    """阿里云 DashScope Embedding"""
    from langchain_community.embeddings import DashScopeEmbeddings

    embedding_model = DashScopeEmbeddings(
        model=model_name,
        dashscope_api_key=api_key,
    )
    vectors = embedding_model.embed_documents(texts)
    return vectors


def _embed_openai(model_name: str, api_key: str | None, texts: list[str]) -> list[list[float]]:
    """OpenAI Embedding（预留）"""
    from openai import OpenAI

    client = OpenAI(api_key=api_key)
    resp = client.embeddings.create(model=model_name, input=texts)
    return [d.embedding for d in resp.data]


def _embed_local(model_name: str, texts: list[str]) -> list[list[float]]:
    """本地 Embedding（sentence-transformers），首次自动下载模型"""
    from pathlib import Path
    from sentence_transformers import SentenceTransformer

    from backend.core.config import settings

    cache_dir = Path(settings.embedding.model_cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    model = SentenceTransformer(model_name, cache_folder=str(cache_dir))
    results = model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
    return results.tolist()
