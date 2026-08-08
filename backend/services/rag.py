"""
RAG 对话服务：检索 → 组装 prompt → LLM 生成

- chat():       非流式，返回 ChatResponse
- chat_stream(): 流式，产出 SSE 事件 dict
- 前置校验抽取为 _load_agent_context，chat / chat_stream 共用
"""
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.config import settings
from backend.models import Agents, KnowledgeBases, UserModelConfig, Users
from backend.repositories import AgentRepo, DocumentRepo, KnowledgeBaseRepo, UserModelConfigRepo
from backend.schemas.agent import ChatRequest, ChatResponse, Citation
from backend.services.embedding import EmbeddingService
from backend.services.llm import LLMService

logger = logging.getLogger(__name__)


class RAGService:
    """RAG 对话编排：检索 + 组装 + LLM 生成"""

    # ═══════════════════════════════════════════════
    # 非流式
    # ═══════════════════════════════════════════════

    @staticmethod
    async def chat(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
    ) -> ChatResponse:
        """
        非流式对话

        流程：校验 Agent/知识库 → 向量化 query → 检索 top_k → 组装 prompt → LLM 生成
        返回 answer + citations
        """
        agent, kb, emb_cfg, llm_cfg = await RAGService._load_agent_context(db, user, agent_id)

        # 1. 向量化 query（零填充到 max_dimension）
        vec = EmbeddingService.embed(
            provider=emb_cfg.provider,
            model_name=emb_cfg.model_name,
            api_key=emb_cfg.api_key,
            base_url=emb_cfg.base_url,
            texts=[request.message],
        )[0]
        max_dim = settings.embedding.max_dimension
        if len(vec) < max_dim:
            vec = list(vec) + [0.0] * (max_dim - len(vec))

        # 2. 检索
        rows = await DocumentRepo.search_chunks(db, kb.id, vec, agent.top_k)
        citations = [
            Citation(
                chunk_id=r["chunk_id"],
                document_name=r["filename"],
                content=r["content"],
                score=round(r["score"], 4),
            )
            for r in rows
            if r["score"] >= agent.score_threshold
        ]

        # 3. 无命中 → 短路返回，不调 LLM
        if not citations:
            return ChatResponse(answer="知识库中没有相关信息。", citations=[])

        # 4. 组装 messages 并调用 LLM
        messages = RAGService._build_messages(agent, request, citations)
        try:
            answer = await LLMService.chat(
                provider=llm_cfg.provider,
                model_name=llm_cfg.model_name,
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                messages=messages,
                temperature=agent.temperature,
                top_p=agent.top_p,
            )
        except Exception as e:
            logger.error(f"LLM 调用失败: {e}")
            raise HTTPException(status_code=502, detail=f"LLM 服务调用失败: {e}")

        return ChatResponse(answer=answer, citations=citations)

    # ═══════════════════════════════════════════════
    # 流式
    # ═══════════════════════════════════════════════

    @staticmethod
    async def chat_stream(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
    ) -> AsyncIterator[dict]:
        """
        流式对话，产出 SSE 事件 dict

        事件序列：{"type": "delta", "content": ...} × N
                 → {"type": "citations", "citations": [...]}
                 → {"type": "done"}
        """
        agent, kb, emb_cfg, llm_cfg = await RAGService._load_agent_context(db, user, agent_id)

        vec = EmbeddingService.embed(
            provider=emb_cfg.provider,
            model_name=emb_cfg.model_name,
            api_key=emb_cfg.api_key,
            base_url=emb_cfg.base_url,
            texts=[request.message],
        )[0]
        max_dim = settings.embedding.max_dimension
        if len(vec) < max_dim:
            vec = list(vec) + [0.0] * (max_dim - len(vec))

        rows = await DocumentRepo.search_chunks(db, kb.id, vec, agent.top_k)
        citations = [
            Citation(
                chunk_id=r["chunk_id"],
                document_name=r["filename"],
                content=r["content"],
                score=round(r["score"], 4),
            )
            for r in rows
            if r["score"] >= agent.score_threshold
        ]

        if not citations:
            yield {"type": "delta", "content": "知识库中没有相关信息。"}
            yield {"type": "citations", "citations": []}
            yield {"type": "done"}
            return

        messages = RAGService._build_messages(agent, request, citations)
        try:
            async for delta in LLMService.chat_stream(
                provider=llm_cfg.provider,
                model_name=llm_cfg.model_name,
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                messages=messages,
                temperature=agent.temperature,
                top_p=agent.top_p,
            ):
                yield {"type": "delta", "content": delta}
        except Exception as e:
            logger.error(f"LLM 流式调用失败: {e}")
            yield {"type": "error", "code": 502, "message": f"LLM 服务调用失败: {e}"}
            yield {"type": "done"}
            return

        yield {"type": "citations", "citations": [c.model_dump() for c in citations]}
        yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _load_agent_context(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> tuple[Agents, KnowledgeBases, UserModelConfig, UserModelConfig]:
        """
        加载并校验 Agent 对话上下文

        返回 (agent, kb, emb_cfg, llm_cfg)
        Raises: HTTPException 404/400
        """
        # Agent 校验
        agent = await AgentRepo.get_by_id(db, agent_id)
        if agent is None or agent.status == 9 or agent.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        if agent.status == 0:
            raise HTTPException(status_code=400, detail="Agent 已禁用")

        # 知识库校验
        kb = await KnowledgeBaseRepo.get_by_id(db, agent.kb_id)
        if kb is None or kb.status == 9 or kb.user_id != user.id:
            raise HTTPException(status_code=404, detail="知识库不存在")
        if kb.status == 0:
            raise HTTPException(status_code=400, detail="知识库已禁用")

        # Embedding 配置校验
        if not kb.user_model_config_id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")
        emb_cfg = await UserModelConfigRepo.get_by_id(db, kb.user_model_config_id)
        if emb_cfg is None or emb_cfg.user_id != user.id:
            raise HTTPException(status_code=400, detail="知识库未配置 Embedding 模型")

        # LLM 配置校验
        llm_cfg = await UserModelConfigRepo.get_by_id(db, agent.llm_config_id)
        if llm_cfg is None or llm_cfg.user_id != user.id or llm_cfg.model_type != 2:
            raise HTTPException(status_code=400, detail="LLM 模型配置无效")
        if not llm_cfg.api_key:
            raise HTTPException(status_code=400, detail="LLM 配置缺少 API Key")

        return agent, kb, emb_cfg, llm_cfg

    @staticmethod
    def _build_messages(
        agent: Agents,
        request: ChatRequest,
        citations: list[Citation],
    ) -> list[dict]:
        """
        组装 LLM messages

        system: agent.system_prompt（{agent_name} 占位替换）
        中间: history（最多最近 10 条）
        user:  引用块 + 用户问题
        """
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        for h in request.history[-10:]:
            messages.append({"role": h.role, "content": h.content})

        messages.append({"role": "user", "content": RAGService._build_user_prompt(citations, request.message)})
        return messages

    @staticmethod
    def _build_user_prompt(citations: list[Citation], message: str) -> str:
        """组装带引用块的 user prompt"""
        parts = ["以下是知识库中可能与问题相关的资料片段：", ""]
        for i, c in enumerate(citations, 1):
            parts.append(f"[{i}] （来源：《{c.document_name}》）")
            parts.append(c.content)
            parts.append("")
        parts.append("请基于以上资料回答用户问题。回答中引用资料时标注对应编号。")
        parts.append('如果资料不足以回答，请直接说明"知识库中没有相关信息"。')
        parts.append("")
        parts.append(f"用户问题：{message}")
        return "\n".join(parts)
