"""
Agent 工具：rag（知识库检索）

RAGTool：向量化 query（多 query 预留）→ pgvector 余弦检索 → 阈值过滤 → 去重排序 → 返回引用块

默认值（config.yaml tools 节点）：
  top_k               → tools.default_top_k
  score_threshold     → tools.default_score_threshold
"""
import json
import logging
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.core.utils import to_uuid
from backend.models import Users
from backend.repositories import DocumentRepo, KnowledgeBaseRepo, UserModelConfigRepo
from backend.schemas.agent import Citation
from backend.services.embedding import EmbeddingService
from backend.tools.common.base import BaseTool

logger = logging.getLogger(__name__)

# 工具描述（供 LLM 判断是否调用）
RAG_TOOL_DESCRIPTION = "检索知识库中与用户问题相关的资料片段，返回可能包含答案的引用内容。"


class RAGTool(BaseTool):
    """RAG 检索工具：知识库向量检索，返回命中的引用块列表"""

    type = "rag"
    description = RAG_TOOL_DESCRIPTION
    # 配置中的 kb_id 需要补全知识库名称（响应 kb_name）
    name_ref_keys = {"kb_id": "kb_name"}

    @staticmethod
    async def validate_config(db: AsyncSession, user: Users, config: dict, **kwargs) -> None:
        """
        校验工具配置：kb_id 存在 + 归属当前用户 + 未删除 + 启用

        Raises: HTTPException 404（不存在/已删除/无归属） / 400（已禁用）
        """
        kb_id = to_uuid(config.get("kb_id")) if config.get("kb_id") else None
        if kb_id is None:
            raise HTTPException(status_code=400, detail="rag 工具缺少 kb_id")

        kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
        if kb is None or kb.status == 9 or kb.user_id != user.id:
            raise HTTPException(status_code=404, detail="知识库不存在")
        if kb.status == 0:
            raise HTTPException(status_code=400, detail="知识库已禁用")

    @staticmethod
    def build_langchain(db: AsyncSession, user: Users, config: dict, **kwargs):
        """
        构建 LangChain 工具（闭包绑定 db/user/config，供 create_agent 注册）

        额外参数（kwargs）:
            citations_store: 外部列表，工具执行结果追加至此（响应回传引用）

        LLM 仅需提供 query 参数；工具异常时返回 JSON 错误信息（让 LLM 自行决定下一步）
        """
        from langchain_core.tools import tool

        citations_store = kwargs.get("citations_store")

        @tool
        async def rag(query: str) -> str:
            """检索知识库中与用户问题相关的资料片段，返回可能包含答案的引用内容。"""
            try:
                cits = await RAGTool.execute(db, user, config, message=query)
            except HTTPException as e:
                return json.dumps({"error": e.detail}, ensure_ascii=False)
            if citations_store is not None:
                citations_store.extend(cits)
            return json.dumps([c.model_dump() for c in cits], ensure_ascii=False)

        return rag

    @staticmethod
    async def execute(
        db: AsyncSession,
        user: Users,
        config: dict,
        message: str,
        **kwargs,
    ) -> list[Citation]:
        """
        执行知识库检索

        参数:
            config: 工具配置 {kb_id, top_k, score_threshold}
            message: 用户消息（作为检索 query）

        返回: 命中的引用块列表（已按 score 阈值过滤，按相似度降序，最多 top_k 条）
        """
        kb_id = to_uuid(config.get("kb_id")) if config.get("kb_id") else None
        if kb_id is None:
            raise HTTPException(status_code=400, detail="rag 工具缺少 kb_id")
        top_k = config.get("top_k") or settings.tools.default_top_k
        score_threshold = config.get("score_threshold") or settings.tools.default_score_threshold

        # 1. 知识库校验：归属 + 未删除 + 启用
        await RAGTool.validate_config(db, user, config)

        # 2. Embedding 配置校验
        kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
        if not kb.user_model_config_id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")
        emb_cfg = await UserModelConfigRepo.get_by_id(db, kb.user_model_config_id)
        if emb_cfg is None or emb_cfg.user_id != user.id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")

        # 3. 向量化 query：当前单个 query，预留查询增强（HyDE / 多角度改写 → 多个 query）
        query_vecs = EmbeddingService.embed(
            provider=emb_cfg.provider,
            model_name=emb_cfg.model_name,
            api_key=emb_cfg.api_key,
            base_url=emb_cfg.base_url,
            texts=[message],
        )
        max_dim = settings.embedding.max_dimension

        # 4. 每个 query 独立检索，按 chunk_id 去重（保留最高分）
        seen: dict[UUID, tuple[str, str, float]] = {}
        for qv in query_vecs:
            if len(qv) < max_dim:
                qv = list(qv) + [0.0] * (max_dim - len(qv))
            rows = await DocumentRepo.search_chunks(db, kb.id, qv, top_k)
            for r in rows:
                if r["score"] < score_threshold:
                    continue
                cid = r["chunk_id"]
                if cid not in seen or r["score"] > seen[cid][2]:
                    seen[cid] = (r["content"], r["filename"], r["score"])

        # 5. 按相似度降序，截断 top_k
        ranked = sorted(seen.items(), key=lambda kv: kv[1][2], reverse=True)[:top_k]
        return [
            Citation(
                chunk_id=cid,
                document_name=filename,
                content=content,
                score=round(score, 4),
            )
            for cid, (content, filename, score) in ranked
        ]
