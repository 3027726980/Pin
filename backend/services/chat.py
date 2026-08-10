"""
对话编排服务:按 Agent 类型分发对话(记忆由 checkpoint 持久化)

- 所有类型统一 create_agent + checkpointer(thread_id = conversation_id)
- simple_rag:预检索(代码控制)→ 命中注入引用块;无命中短路 + 手动写 checkpoint
- general:LLM 自主决策工具调用(LangGraph 多轮)
- 每轮对话双写 messages(user 原始问题 + assistant 回答含 citations)
- 短期记忆:SummarizationMiddleware(参数走 config.yaml,总结模型 Agent 级配置)
"""
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk, HumanMessage
from langchain_openai import ChatOpenAI
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import (
    AgentIndexRepo,
    ConversationRepo,
    GeneralAgentRepo,
    MessageRepo,
    SimpleRagAgentRepo,
    UserModelConfigRepo,
)
from backend.schemas.agent import ChatRequest, ChatResponse, Citation
from backend.services.conversation import ConversationService
from backend.services.middleware import build_middlewares
from backend.tools import RAGTool, ToolRegistry

logger = logging.getLogger(__name__)


class ChatService:
    """对话编排:checkpoint 记忆 + 双写留痕"""

    # ═══════════════════════════════════════════════
    # 入口
    # ═══════════════════════════════════════════════

    @staticmethod
    async def chat(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
    ) -> ChatResponse:
        """非流式对话(记忆由 checkpoint 持久化,双写 messages)"""
        atype, agent, llm_cfg, conv = await ChatService._load_context(
            db, user, agent_id, request.conversation_id)

        if atype == "simple_rag":
            answer, citations = await ChatService._chat_simple_rag(
                db, user, agent, llm_cfg, conv, request)
        else:
            answer, citations = await ChatService._chat_general(
                db, user, agent, llm_cfg, conv, request)

        await ChatService._persist_messages(
            db, conv.id, request.message, answer, citations)
        return ChatResponse(conversation_id=conv.id, answer=answer,
                            citations=citations)

    @staticmethod
    async def chat_stream(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
    ) -> AsyncIterator[dict]:
        """流式对话,产出 SSE 事件 dict;流结束(含异常)后双写 messages"""
        atype, agent, llm_cfg, conv = await ChatService._load_context(
            db, user, agent_id, request.conversation_id)
        full_answer: list[str] = []
        citations: list[Citation] = []
        try:
            if atype == "simple_rag":
                async for event in ChatService._chat_simple_rag_stream(
                        db, user, agent, llm_cfg, conv, request,
                        full_answer, citations):
                    yield event
            else:
                async for event in ChatService._chat_general_stream(
                        db, user, agent, llm_cfg, conv, request,
                        full_answer, citations):
                    yield event
        finally:
            await ChatService._persist_messages(
                db, conv.id, request.message, "".join(full_answer), citations)

    # ═══════════════════════════════════════════════
    # simple_rag(预检索 + create_agent)
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _chat_simple_rag(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        conv: object,
        request: ChatRequest,
    ) -> tuple[str, list[Citation]]:
        """预检索 → 命中注入引用块走 create_agent;无命中短路 + 手动写 checkpoint"""
        config = {"type": "rag", "kb_id": str(agent.kb_id),
                  "top_k": agent.top_k, "score_threshold": agent.score_threshold}
        citations = await RAGTool.execute(db, user, config, request.message)

        if not citations:
            await ChatService._persist_turn_without_llm(conv.id, request.message)
            return "知识库中没有相关信息。", []

        user_content = ChatService._build_user_prompt(citations, request.message)
        answer = await ChatService._invoke_agent(
            db, user, agent, llm_cfg, conv, tools=[], user_content=user_content)
        return answer, citations

    @staticmethod
    async def _chat_simple_rag_stream(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        conv: object,
        request: ChatRequest,
        full_answer: list[str],
        citations: list[Citation],
    ) -> AsyncIterator[dict]:
        """simple_rag 流式:预检索 → 命中流式生成;无命中短路 + 持久化"""
        config = {"type": "rag", "kb_id": str(agent.kb_id),
                  "top_k": agent.top_k, "score_threshold": agent.score_threshold}
        refs = await RAGTool.execute(db, user, config, request.message)
        if not refs:
            await ChatService._persist_turn_without_llm(conv.id, request.message)
            full_answer.append("知识库中没有相关信息。")
            yield {"type": "delta", "content": "知识库中没有相关信息。"}
            yield {"type": "citations", "citations": []}
            yield {"type": "done"}
            return
        citations.extend(refs)
        user_content = ChatService._build_user_prompt(refs, request.message)
        async for event in ChatService._invoke_agent_stream(
                db, user, agent, llm_cfg, conv, tools=[],
                user_content=user_content):
            if event.get("type") == "delta":
                full_answer.append(event["content"])
            yield event
        yield {"type": "citations",
               "citations": [c.model_dump(mode="json") for c in refs]}
        yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # general(LLM 自主决策)
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _chat_general(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        conv: object,
        request: ChatRequest,
    ) -> tuple[str, list[Citation]]:
        """general:create_agent 自主决策(工具 + checkpoint 记忆)"""
        citations_store: list[Citation] = []
        tools = ToolRegistry.build_langchain_tools(
            db, user, agent.tools, citations_store=citations_store)
        answer = await ChatService._invoke_agent(
            db, user, agent, llm_cfg, conv, tools=tools,
            user_content=request.message, citations_store=citations_store)
        return answer, citations_store

    @staticmethod
    async def _chat_general_stream(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        conv: object,
        request: ChatRequest,
        full_answer: list[str],
        citations: list[Citation],
    ) -> AsyncIterator[dict]:
        """general 流式:create_agent.astream(工具调用轮不输出)"""
        citations_store: list[Citation] = []
        tools = ToolRegistry.build_langchain_tools(
            db, user, agent.tools, citations_store=citations_store)
        async for event in ChatService._invoke_agent_stream(
                db, user, agent, llm_cfg, conv, tools=tools,
                user_content=request.message, citations_store=citations_store):
            if event.get("type") == "delta":
                full_answer.append(event["content"])
            yield event
        citations.extend(citations_store)
        yield {"type": "citations",
               "citations": [c.model_dump(mode="json") for c in citations_store]}
        yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # create_agent 统一调用
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _get_summary_cfg(db: AsyncSession, user: Users, agent: object):
        """总结模型配置:agent.summary_llm_config_id → user_model_config(失效时回退 None)"""
        if not agent.summary_llm_config_id:
            return None
        cfg = await UserModelConfigRepo.get_by_id(db, agent.summary_llm_config_id)
        if cfg is None or cfg.user_id != user.id or cfg.model_type != 2:
            return None  # 配置失效时静默回退到对话模型
        return cfg

    @staticmethod
    async def _build_agent(db: AsyncSession, user: Users, agent: object,
                           llm_cfg: object, tools: list) -> object:
        """构建 create_agent(带 checkpointer + middleware)"""
        from backend.core.checkpointer import get_checkpointer

        summary_cfg = await ChatService._get_summary_cfg(db, user, agent)
        middlewares = build_middlewares(summary_cfg, llm_cfg)
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        cp = await get_checkpointer()
        return create_agent(
            model=ChatOpenAI(
                model=llm_cfg.model_name, api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url or "https://api.openai.com/v1",
                temperature=agent.temperature, top_p=agent.top_p, timeout=60.0),
            tools=tools, system_prompt=system_prompt,
            checkpointer=cp, middleware=middlewares)

    @staticmethod
    def _thread_config(conv: object) -> dict:
        """checkpoint thread 配置(thread_id = conversation_id)"""
        return {"configurable": {"thread_id": str(conv.id), "checkpoint_ns": ""}}

    @staticmethod
    async def _invoke_agent(db: AsyncSession, user: Users, agent: object,
                            llm_cfg: object, conv: object, tools: list,
                            user_content: str,
                            citations_store: list | None = None) -> str:
        """非流式:create_agent.ainvoke(thread_id = conversation_id)"""
        lc_agent = await ChatService._build_agent(db, user, agent, llm_cfg, tools)
        try:
            result = await lc_agent.ainvoke(
                {"messages": [HumanMessage(content=user_content)]},
                config=ChatService._thread_config(conv))
            return result["messages"][-1].content or ""
        except Exception as e:
            logger.error(f"Agent 调用失败: {e}")
            raise HTTPException(status_code=502, detail=f"LLM 服务调用失败: {e}")

    @staticmethod
    async def _invoke_agent_stream(db: AsyncSession, user: Users, agent: object,
                                   llm_cfg: object, conv: object, tools: list,
                                   user_content: str,
                                   citations_store: list | None = None
                                   ) -> AsyncIterator[dict]:
        """流式:create_agent.astream(stream_mode='messages',工具轮自动跳过)"""
        lc_agent = await ChatService._build_agent(db, user, agent, llm_cfg, tools)
        try:
            async for chunk, _meta in lc_agent.astream(
                    {"messages": [HumanMessage(content=user_content)]},
                    config=ChatService._thread_config(conv),
                    stream_mode="messages"):
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield {"type": "delta", "content": chunk.content}
        except Exception as e:
            logger.error(f"Agent 流式调用失败: {e}")
            yield {"type": "error", "code": 502,
                   "message": f"LLM 服务调用失败: {e}"}
            yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _load_context(db: AsyncSession, user: Users, agent_id: UUID,
                            conversation_id: UUID | None):
        """定位 Agent + 校验 LLM 配置 + 获取/创建会话"""
        atype, agent, llm_cfg = await ChatService._load_agent_context(
            db, user, agent_id)
        conv = await ChatService._get_or_create_conversation(
            db, user, agent_id, conversation_id)
        return atype, agent, llm_cfg, conv

    @staticmethod
    async def _get_or_create_conversation(db: AsyncSession, user: Users,
                                          agent_id: UUID,
                                          conversation_id: UUID | None):
        """获取会话(校验归属 + Agent 匹配)或自动创建"""
        if conversation_id is None:
            resp = await ConversationService.create(db, user, agent_id)
            return await ConversationRepo.get_by_id(db, resp.id)
        conv = await ConversationRepo.get_by_id(db, conversation_id)
        if conv is None or conv.status == 9 or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        if conv.agent_id != agent_id:
            raise HTTPException(status_code=400, detail="会话与 Agent 不匹配")
        return conv

    @staticmethod
    async def _load_agent_context(db: AsyncSession, user: Users,
                                  agent_id: UUID) -> tuple[str, object, object]:
        """
        定位 Agent(索引表 → 类型表)并校验 LLM 配置

        返回 (type, agent_orm, llm_cfg)
        Raises: HTTPException 404/400
        """
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is None or entry.status == 9 or entry.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")

        if entry.type == "simple_rag":
            agent = await SimpleRagAgentRepo.get_by_id(db, agent_id)
            atype = "simple_rag"
        else:
            agent = await GeneralAgentRepo.get_by_id(db, agent_id)
            atype = "general"

        if agent is None or agent.status == 9:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        if agent.status == 0:
            raise HTTPException(status_code=400, detail="Agent 已禁用")

        llm_cfg = await UserModelConfigRepo.get_by_id(db, agent.llm_config_id)
        if llm_cfg is None or llm_cfg.user_id != user.id or llm_cfg.model_type != 2:
            raise HTTPException(status_code=400, detail="LLM 模型配置无效")
        if not llm_cfg.api_key:
            raise HTTPException(status_code=400, detail="LLM 配置缺少 API Key")

        return atype, agent, llm_cfg

    @staticmethod
    async def _persist_turn_without_llm(conversation_id: UUID,
                                        user_message: str) -> None:
        """无命中短路:把 user + assistant 消息手动写入 checkpoint"""
        from langchain_core.messages import AIMessage

        from backend.core.checkpointer import get_checkpointer

        cp = await get_checkpointer()
        config = {"configurable": {"thread_id": str(conversation_id),
                                   "checkpoint_ns": ""}}
        tup = await cp.aget_tuple(config)
        if tup is None:
            from langgraph.checkpoint.base import Checkpoint

            checkpoint = Checkpoint(
                v=1,
                ts=datetime.now(timezone.utc).isoformat(),
                id=str(uuid4()),
                channel_values={"messages": []},
                channel_versions={"messages": 1},
                versions_seen={},
                pending_sends=[],
            )
            messages: list = []
            metadata: dict = {}
            new_versions: dict = {"messages": 1}
        else:
            checkpoint = tup.checkpoint
            messages = list(checkpoint.get("channel_values", {}).get("messages", []))
            metadata = tup.metadata or {}
            new_versions = tup.new_versions or {}

        messages.append(HumanMessage(content=user_message))
        messages.append(AIMessage(content="知识库中没有相关信息。"))
        checkpoint["channel_values"]["messages"] = messages
        await cp.aput(config, checkpoint, metadata, new_versions)

    @staticmethod
    async def _persist_messages(db: AsyncSession, conversation_id: UUID,
                                user_msg: str, assistant_msg: str,
                                citations: list[Citation]) -> None:
        """双写 messages 表(user 原始问题 + assistant 回答含引用)"""
        await MessageRepo.create(db, conversation_id, "user", user_msg, None)
        await MessageRepo.create(
            db, conversation_id, "assistant", assistant_msg,
            [c.model_dump(mode="json") for c in citations] if citations else None)
        await db.commit()

    @staticmethod
    def _build_user_prompt(citations: list[Citation], message: str) -> str:
        """组装带引用块的 user prompt(simple_rag 用)"""
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
