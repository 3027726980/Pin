"""
对话编排服务：按 Agent 类型分发对话

- simple_rag：代码控制（固定执行 RAG 检索 → 组装 prompt → LLM 生成）
  —— 可靠性优先：每次提问必定检索，无命中短路返回
- general：LLM 自主决策（LangChain create_agent）
  —— 模型自行判断是否调用工具（RAG 等），可能多轮工具调用，可能纯 LLM 回答
"""
import logging
from collections.abc import AsyncIterator
from uuid import UUID

from fastapi import HTTPException
from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import (
    GeneralAgentRepo,
    SimpleRagAgentRepo,
    UserModelConfigRepo,
)
from backend.schemas.agent import ChatRequest, ChatResponse, Citation
from backend.services.llm import LLMService
from backend.tools import RAGTool, ToolRegistry

logger = logging.getLogger(__name__)


class ChatService:
    """对话编排：按类型获取引用（代码控制 / LLM 自主）+ LLM 生成"""

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

        simple_rag：代码控制检索 → 无命中短路 → LLM 生成
        general：create_agent 自主决策（模型决定是否调用工具）
        """
        atype, agent, llm_cfg = await ChatService._load_agent_context(db, user, agent_id)

        if atype == "simple_rag":
            return await ChatService._chat_simple_rag(db, user, agent, llm_cfg, request)
        return await ChatService._chat_general(db, user, agent, llm_cfg, request)

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
        atype, agent, llm_cfg = await ChatService._load_agent_context(db, user, agent_id)

        if atype == "simple_rag":
            async for event in ChatService._chat_simple_rag_stream(db, user, agent, llm_cfg, request):
                yield event
        else:
            async for event in ChatService._chat_general_stream(db, user, agent, llm_cfg, request):
                yield event

    # ═══════════════════════════════════════════════
    # simple_rag（代码控制）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _chat_simple_rag(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        request: ChatRequest,
    ) -> ChatResponse:
        """简单 RAG：固定执行检索 → 无命中短路 → 组装 prompt → LLM 生成"""
        config = {
            "type": "rag",
            "kb_id": str(agent.kb_id),
            "top_k": agent.top_k,
            "score_threshold": agent.score_threshold,
        }
        citations = await RAGTool.execute(db, user, config, request.message)

        if not citations:
            return ChatResponse(answer="知识库中没有相关信息。", citations=[])

        messages = ChatService._build_messages(agent, request, citations)
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

    @staticmethod
    async def _chat_simple_rag_stream(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        request: ChatRequest,
    ) -> AsyncIterator[dict]:
        """简单 RAG 流式：检索 → 无命中短路 → 流式生成"""
        config = {
            "type": "rag",
            "kb_id": str(agent.kb_id),
            "top_k": agent.top_k,
            "score_threshold": agent.score_threshold,
        }
        citations = await RAGTool.execute(db, user, config, request.message)

        if not citations:
            yield {"type": "delta", "content": "知识库中没有相关信息。"}
            yield {"type": "citations", "citations": []}
            yield {"type": "done"}
            return

        messages = ChatService._build_messages(agent, request, citations)
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
    # general（LLM 自主决策，LangChain create_agent）
    # ═══════════════════════════════════════════════

    @staticmethod
    def _build_general_agent(agent, llm_cfg, tools, system_prompt):
        """构建 LangChain create_agent（模型 + 工具 + 系统提示词）"""
        model = ChatOpenAI(
            model=llm_cfg.model_name,
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url or "https://api.openai.com/v1",
            temperature=agent.temperature,
            top_p=agent.top_p,
            timeout=60.0,
        )
        return create_agent(
            model=model,
            tools=tools,
            system_prompt=system_prompt,
        )

    @staticmethod
    async def _chat_general(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        request: ChatRequest,
    ) -> ChatResponse:
        """综合 Agent：create_agent 自主决策（模型判断是否调用工具，可能多轮）"""
        citations_store: list[Citation] = []
        tools = ToolRegistry.build_langchain_tools(db, user, agent.tools, citations_store)
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        lc_agent = ChatService._build_general_agent(agent, llm_cfg, tools, system_prompt)

        messages: list = [(h.role, h.content) for h in request.history[-10:]]
        messages.append(("user", request.message))

        try:
            result = await lc_agent.ainvoke({"messages": messages})
            answer = result["messages"][-1].content or ""
        except Exception as e:
            logger.error(f"general Agent 调用失败: {e}")
            raise HTTPException(status_code=502, detail=f"LLM 服务调用失败: {e}")

        return ChatResponse(answer=answer, citations=citations_store)

    @staticmethod
    async def _chat_general_stream(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        request: ChatRequest,
    ) -> AsyncIterator[dict]:
        """综合 Agent 流式：create_agent.astream 逐 token 输出（工具调用轮不输出）"""
        citations_store: list[Citation] = []
        tools = ToolRegistry.build_langchain_tools(db, user, agent.tools, citations_store)
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        lc_agent = ChatService._build_general_agent(agent, llm_cfg, tools, system_prompt)

        messages: list = [(h.role, h.content) for h in request.history[-10:]]
        messages.append(("user", request.message))

        try:
            async for chunk, _meta in lc_agent.astream({"messages": messages}, stream_mode="messages"):
                # 只输出 AI 生成的内容增量（工具调用/工具结果轮次无 content，自动跳过）
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield {"type": "delta", "content": chunk.content}
        except Exception as e:
            logger.error(f"general Agent 流式调用失败: {e}")
            yield {"type": "error", "code": 502, "message": f"LLM 服务调用失败: {e}"}
            yield {"type": "done"}
            return

        yield {"type": "citations", "citations": [c.model_dump() for c in citations_store]}
        yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _load_agent_context(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
    ) -> tuple[str, object, object]:
        """
        定位 Agent（按类型）并校验 LLM 配置

        返回 (type, agent_orm, llm_cfg)
        Raises: HTTPException 404/400
        """
        # 先查 general，再查 simple_rag
        agent = await GeneralAgentRepo.get_by_id(db, agent_id)
        atype = "general"
        if agent is None or agent.status == 9 or agent.user_id != user.id:
            agent = await SimpleRagAgentRepo.get_by_id(db, agent_id)
            atype = "simple_rag"

        if agent is None or agent.status == 9 or agent.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        if agent.status == 0:
            raise HTTPException(status_code=400, detail="Agent 已禁用")

        # LLM 配置校验
        llm_cfg = await UserModelConfigRepo.get_by_id(db, agent.llm_config_id)
        if llm_cfg is None or llm_cfg.user_id != user.id or llm_cfg.model_type != 2:
            raise HTTPException(status_code=400, detail="LLM 模型配置无效")
        if not llm_cfg.api_key:
            raise HTTPException(status_code=400, detail="LLM 配置缺少 API Key")

        return atype, agent, llm_cfg

    @staticmethod
    def _build_messages(
        agent: object,
        request: ChatRequest,
        citations: list[Citation],
    ) -> list[dict]:
        """
        组装 LLM messages（simple_rag 用）

        system: agent.system_prompt（{agent_name} 占位替换）
        中间: history（最多最近 10 条）
        user:  引用块 + 用户问题
        """
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        messages: list[dict] = [{"role": "system", "content": system_prompt}]

        for h in request.history[-10:]:
            messages.append({"role": h.role, "content": h.content})

        messages.append({"role": "user", "content": ChatService._build_user_prompt(citations, request.message)})
        return messages

    @staticmethod
    def _build_user_prompt(citations: list[Citation], message: str) -> str:
        """组装带引用块的 user prompt（simple_rag 用）"""
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
