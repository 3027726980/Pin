"""
Rerank 服务 — 按 provider 分发（local / aliyun）

- local：本地 CrossEncoder（sentence-transformers），local_files_only，CPU 推理走 asyncio.to_thread 防阻塞事件循环
- aliyun：DashScope Rerank API（httpx 异步直连）

新增厂商 = 实现一个类（rerank 静态方法）+ 注册到 RERANK_IMPLEMENTATIONS，调用方零改动。
任何失败（模型缺失 / API 异常 / 未知 provider）→ logger.warning + 原样返回候选（降级不阻断）。
"""
import logging
from types import SimpleNamespace

from backend.core.config import settings

logger = logging.getLogger(__name__)


class RerankService:
    """Rerank 精排统一入口：按 provider 分发，cfg 为空时用 config.yaml tools.rerank 全局默认"""

    @staticmethod
    async def rerank(cfg, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """
        精排候选列表，返回 top_k 条（score 字段替换为 reranker 分数）

        参数:
            cfg: user_model_config ORM（provider / model_name / api_key / base_url）；
                 None 时用 tools.rerank 全局默认（local 模型）
            query: 检索原始用户问题（精排相关性基准）
            candidates: 粗召回候选 [{chunk_id, content, filename, score}, ...]
            top_k: 返回条数

        返回: 精排后的候选列表；失败降级返回原候选（不抛异常）
        """
        if cfg is None:
            cfg = SimpleNamespace(
                provider="local",
                model_name=settings.local_models.rerank.model_name,
                api_key=None,
                base_url=None,
            )
        impl = RERANK_IMPLEMENTATIONS.get(cfg.provider)
        if impl is None:
            logger.warning("未知 rerank provider: %s，降级纯向量排序", cfg.provider)
            return candidates[:top_k]
        try:
            return await impl.rerank(cfg, query, candidates, top_k)
        except Exception as e:
            logger.warning("rerank 执行失败（provider=%s）: %s，降级纯向量排序", cfg.provider, e)
            return candidates[:top_k]


class LocalRerank:
    """本地 CrossEncoder 精排：进程内单例缓存 + asyncio.to_thread 推理"""

    _model = None
    _model_key = None  # 当前加载的模型标识（模型名变更时重新加载）

    @staticmethod
    async def rerank(cfg, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """本地模型精排：模型目录 <cache_dir>/<model_name>，缺失抛 FileNotFoundError（上层降级）"""
        import asyncio
        from pathlib import Path

        cache_dir = Path(settings.local_models.cache_dir)
        model_dir = cache_dir / cfg.model_name
        if not model_dir.exists():
            raise FileNotFoundError(
                f"本地 rerank 模型不存在: {model_dir}，请先下载模型到该目录"
            )

        key = f"{cfg.model_name}|{settings.local_models.rerank.device}"
        if LocalRerank._model is None or LocalRerank._model_key != key:
            from sentence_transformers import CrossEncoder

            LocalRerank._model = CrossEncoder(
                str(model_dir),
                device=settings.local_models.rerank.device,
                local_files_only=True,
            )
            LocalRerank._model_key = key

        model = LocalRerank._model
        pairs = [(query, c["content"]) for c in candidates]

        def _predict():
            scores = model.predict(pairs)
            return [float(s) for s in scores]

        # CPU 推理同步阻塞，丢线程池防事件循环卡死
        scores = await asyncio.to_thread(_predict)

        ranked = sorted(
            zip(candidates, scores),
            key=lambda x: x[1],
            reverse=True,
        )[:top_k]
        return [
            {**c, "score": round(s, 4)} for c, s in ranked
        ]


class DashScopeRerank:
    """DashScope（阿里云百炼）Rerank API：httpx 异步直连"""

    _ENDPOINT = "/services/rerank/text-rerank/text-rerank"

    @staticmethod
    async def rerank(cfg, query: str, candidates: list[dict], top_k: int) -> list[dict]:
        """DashScope text-rerank：POST {base_url}{endpoint}，解析 output.results[].relevance_score

        注意：OpenAI 兼容模式地址（含 /compatible-mode/）不提供 Rerank 服务，
        检测到直接报清晰错误（引导用户改用原生 DashScope 地址）。
        """
        import httpx

        if not cfg.api_key:
            raise ValueError("DashScope rerank 缺少 api_key")
        base = (cfg.base_url or "https://dashscope.aliyuncs.com/api/v1").rstrip("/")
        if "/compatible-mode" in base:
            raise ValueError(
                "检测到 OpenAI 兼容模式地址（compatible-mode），该模式不支持 Rerank API；"
                "请改用原生 DashScope 地址：https://dashscope.aliyuncs.com/api/v1 "
                "（专属网关则为 https://llm-xxx.maas.aliyuncs.com/api/v1）")
        url = base + DashScopeRerank._ENDPOINT
        body = {
            "model": cfg.model_name,
            "input": {"query": query, "documents": [c["content"] for c in candidates]},
            "parameters": {"top_n": top_k, "return_documents": False},
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.post(
                url,
                json=body,
                headers={"Authorization": f"Bearer {cfg.api_key}"},
            )
            resp.raise_for_status()
            data = resp.json()

        results = (data.get("output") or {}).get("results") or []
        # results[].{index, relevance_score} → 映射回候选（按原始下标，避免重复 dict 误判）
        by_index = {r.get("index"): float(r.get("relevance_score", 0.0)) for r in results}
        ranked = sorted(
            ((i, c) for i, c in enumerate(candidates) if i in by_index),
            key=lambda x: by_index[x[0]],
            reverse=True,
        )[:top_k]
        return [{**c, "score": round(by_index[i], 4)} for i, c in ranked]


# provider → 实现类 注册表（新增厂商 = 实现类 + 注册一行）
RERANK_IMPLEMENTATIONS: dict[str, type] = {
    "local": LocalRerank,
    "aliyun": DashScopeRerank,
}

__all__ = ["RerankService", "LocalRerank", "DashScopeRerank"]
