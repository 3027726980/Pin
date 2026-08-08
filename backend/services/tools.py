"""
Agent 工具注册表

工具 = 一个可执行的能力单元（type + execute），工具自带配置。
MVP 仅提供 rag（知识库检索）；后续新增工具只需注册新类并在
ToolRegistry.TOOLS 中登记，创建 Agent 时传入对应 type 即可。

执行入口：
    ToolRegistry.execute_all(db, user, tools, message)
    → {tool_type: 工具输出}，各工具输出结构由工具自身定义
"""
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models import Users
from backend.repositories import DocumentRepo, KnowledgeBaseRepo, UserModelConfigRepo
from backend.schemas.agent import Citation
from backend.services.embedding import EmbeddingService

logger = logging.getLogger(__name__)


class RAGTool:
    """RAG 检索工具：向量化 query → pgvector 余弦检索 → 阈值过滤 → 返回引用块"""

    type = "rag"

    @staticmethod
    async def execute(
        db: AsyncSession,
        user: Users,
        config: dict,
        message: str,
    ) -> list[Citation]:
        """
        执行知识库检索

        参数:
            config: 工具配置 {kb_id, top_k, score_threshold}
            message: 用户消息（作为检索 query）

        返回: 命中的引用块列表（已按 score 阈值过滤，按相似度降序）
        """
        kb_id = UUID(config.get("kb_id")) if config.get("kb_id") else None
        if kb_id is None:
            raise HTTPException(status_code=400, detail="rag 工具缺少 kb_id")
        top_k = config.get("top_k", 5)
        score_threshold = config.get("score_threshold", 0.3)

        # 1. 知识库校验：归属 + 未删除 + 启用
        kb = await KnowledgeBaseRepo.get_by_id(db, kb_id)
        if kb is None or kb.status == 9 or kb.user_id != user.id:
            raise HTTPException(status_code=404, detail="知识库不存在")
        if kb.status == 0:
            raise HTTPException(status_code=400, detail="知识库已禁用")

        # 2. Embedding 配置校验
        if not kb.user_model_config_id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")
        emb_cfg = await UserModelConfigRepo.get_by_id(db, kb.user_model_config_id)
        if emb_cfg is None or emb_cfg.user_id != user.id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")

        # 3. 向量化 query（零填充到 max_dimension）
        vec = EmbeddingService.embed(
            provider=emb_cfg.provider,
            model_name=emb_cfg.model_name,
            api_key=emb_cfg.api_key,
            base_url=emb_cfg.base_url,
            texts=[message],
        )[0]
        max_dim = settings.embedding.max_dimension
        if len(vec) < max_dim:
            vec = list(vec) + [0.0] * (max_dim - len(vec))

        # 4. 检索 + 阈值过滤
        rows = await DocumentRepo.search_chunks(db, kb.id, vec, top_k)
        return [
            Citation(
                chunk_id=r["chunk_id"],
                document_name=r["filename"],
                content=r["content"],
                score=round(r["score"], 4),
            )
            for r in rows
            if r["score"] >= score_threshold
        ]


class ToolRegistry:
    """工具注册表：按 type 分发执行"""

    TOOLS: dict[str, type] = {
        "rag": RAGTool,
    }

    @staticmethod
    async def execute_all(
        db: AsyncSession,
        user: Users,
        tools: list[dict],
        message: str,
    ) -> dict[str, list]:
        """
        执行 Agent 的全部工具

        参数:
            tools: 工具配置列表（来自 agents.tools）
            message: 用户消息

        返回: {tool_type: 工具输出}，如 {"rag": [Citation, ...]}
        """
        results: dict[str, list] = {}
        for tool in tools:
            tool_cls = ToolRegistry.TOOLS.get(tool.get("type"))
            if tool_cls is None:
                raise HTTPException(status_code=400, detail=f"不支持的工具类型: {tool.get('type')}")
            results[tool_cls.type] = await tool_cls.execute(db, user, tool, message)
        return results
