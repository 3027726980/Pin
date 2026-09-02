"""
对话编排服务:按 Agent 类型分发对话(记忆由 checkpoint 持久化)

- 所有类型统一 create_agent + checkpointer(thread_id = conversation_id)
- simple_rag:预检索(代码控制)→ 命中注入引用块;无命中短路 + 手动写 checkpoint
- general:LLM 自主决策工具调用(LangGraph 多轮)
- 每轮对话原子追加到会话 JSON(user 原始问题 + assistant 回答含 citations)
- 短期记忆:SummarizationMiddleware(参数走 config.yaml,总结模型 Agent 级配置)
"""
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from uuid import UUID, uuid4

from fastapi import HTTPException
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
from backend.core.config import settings

logger = logging.getLogger(__name__)
_llm_logger = logging.getLogger("backend.llm")  # 链路日志：LLM 调用（写 llm.log）

# ── simple_rag 提示词模板（引用块组装用，见 _build_user_prompt）──────────
_RAG_PROMPT_HEADER = "以下是知识库中可能与问题相关的资料片段："
_RAG_PROMPT_FOOTER = (
    "请基于以上资料回答用户问题。回答中引用资料时标注对应编号。\n"
    '如果资料不足以回答，请直接说明"知识库中没有相关信息"。'
)


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
        client_id: str | None = None,
        exec_user: Users | None = None,
    ) -> ChatResponse:
        """非流式对话(记忆由 checkpoint 持久化,原子追加会话 JSON)

        client_id 非空 = 匿名访客场景（会话归属 client_id，user 为 Agent 所有者）；
        为空 = 登录用户场景（会话归属 user.id）。
        exec_user:公开接口登录场景的 Agent 所有者（agent/LLM 校验身份，会话仍归 user）。
        """
        atype, agent, llm_cfg, conv = await ChatService._load_context(
            db, user, agent_id, request.conversation_id, client_id, exec_user)

        debug_store: dict | None = {} if request.debug else None
        if atype == "simple_rag":
            answer, citations = await ChatService._chat_simple_rag(
                db, user, agent, llm_cfg, conv, request, debug_store=debug_store)
        else:
            intent = await ChatService._classify_intent(
                agent, llm_cfg, request.message)
            if debug_store is not None:
                debug_store["intent"] = intent
            if intent == "simple":
                answer, citations = await ChatService._chat_simple(
                    db, user, agent, llm_cfg, conv, request, debug_store=debug_store)
            else:
                answer, citations = await ChatService._chat_general(
                    db, user, agent, llm_cfg, conv, request, debug_store=debug_store)

        await ChatService._persist_messages(
            db, conv, request.message, answer, citations)
        return ChatResponse(conversation_id=conv.id, answer=answer,
                            citations=citations, debug=debug_store)

    @staticmethod
    async def chat_stream(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
        client_id: str | None = None,
        exec_user: Users | None = None,
    ) -> AsyncIterator[dict]:
        """流式对话,产出 SSE 事件 dict;流结束(含异常)后原子追加会话 JSON

        client_id 非空 = 匿名访客场景（会话归属 client_id）；
        exec_user:公开接口登录场景的 Agent 所有者。
        """
        atype, agent, llm_cfg, conv = await ChatService._load_context(
            db, user, agent_id, request.conversation_id, client_id, exec_user)
        full_answer: list[str] = []
        citations: list[Citation] = []
        debug_store: dict | None = {} if request.debug else None
        try:
            if atype == "simple_rag":
                async for event in ChatService._chat_simple_rag_stream(
                        db, user, agent, llm_cfg, conv, request,
                        full_answer, citations, debug_store=debug_store):
                    yield event
            else:
                intent = await ChatService._classify_intent(
                    agent, llm_cfg, request.message)
                if debug_store is not None:
                    debug_store["intent"] = intent
                yield {"type": "intent", "intent": intent}
                if intent == "simple":
                    async for event in ChatService._chat_simple_stream(
                            db, user, agent, llm_cfg, conv, request,
                            full_answer, citations, debug_store=debug_store):
                        yield event
                else:
                    async for event in ChatService._chat_general_stream(
                            db, user, agent, llm_cfg, conv, request,
                            full_answer, citations, debug_store=debug_store):
                        yield event
        finally:
            await ChatService._persist_messages(
                db, conv, request.message, "".join(full_answer), citations)

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
        debug_store: dict | None = None,
    ) -> tuple[str, list[Citation]]:
        """预检索 → 命中注入引用块走 create_agent;无命中短路 + 手动写 checkpoint"""
        config = {"type": "rag", "kb_id": str(agent.kb_id),
                  "top_k": agent.top_k, "score_threshold": agent.score_threshold,
                  "mqe_enabled": agent.mqe_enabled, "hyde_enabled": agent.hyde_enabled,
                  "mqe_query_count": agent.mqe_query_count,
                  "rerank_enabled": agent.rerank_enabled}
        enhance_cfg = await ChatService._get_enhance_cfg(db, user, agent)
        if enhance_cfg is None:
            enhance_cfg = llm_cfg  # 跟随对话模型（设计：增强 LLM 空 = 用对话模型）
        rerank_cfg = await ChatService._get_rerank_cfg(db, user, agent)
        citations = await RAGTool.execute(
            db, user, config, request.message,
            enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg, debug_store=debug_store)

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
        debug_store: dict | None = None,
    ) -> AsyncIterator[dict]:
        """simple_rag 流式:预检索 → 命中流式生成;无命中短路 + 持久化"""
        config = {"type": "rag", "kb_id": str(agent.kb_id),
                  "top_k": agent.top_k, "score_threshold": agent.score_threshold,
                  "mqe_enabled": agent.mqe_enabled, "hyde_enabled": agent.hyde_enabled,
                  "mqe_query_count": agent.mqe_query_count,
                  "rerank_enabled": agent.rerank_enabled}
        enhance_cfg = await ChatService._get_enhance_cfg(db, user, agent)
        if enhance_cfg is None:
            enhance_cfg = llm_cfg  # 跟随对话模型（设计：增强 LLM 空 = 用对话模型）
        rerank_cfg = await ChatService._get_rerank_cfg(db, user, agent)
        refs = await RAGTool.execute(
            db, user, config, request.message,
            enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg, debug_store=debug_store)
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
        if debug_store is not None:
            yield {"type": "debug", "debug": debug_store}
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
        debug_store: dict | None = None,
    ) -> tuple[str, list[Citation]]:
        """general:create_agent 自主决策(工具 + checkpoint 记忆)"""
        citations_store: list[Citation] = []
        enhance_cfg = await ChatService._get_enhance_cfg(db, user, agent)
        if enhance_cfg is None:
            enhance_cfg = llm_cfg  # 跟随对话模型（设计：增强 LLM 空 = 用对话模型）
        rerank_cfg = await ChatService._get_rerank_cfg(db, user, agent)
        tools = ToolRegistry.build_langchain_tools(
            db, user, agent.tools, citations_store=citations_store,
            enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg,
            debug_store=debug_store)
        tools_desc = ChatService._business_tools_desc(agent)
        tools = tools + ChatService._build_builtin_tools(
            db, user, agent, llm_cfg, tools_desc, event_sink=None)
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
        debug_store: dict | None = None,
    ) -> AsyncIterator[dict]:
        """general 流式:create_agent.astream(工具调用轮不输出)"""
        citations_store: list[Citation] = []
        enhance_cfg = await ChatService._get_enhance_cfg(db, user, agent)
        if enhance_cfg is None:
            enhance_cfg = llm_cfg  # 跟随对话模型（设计：增强 LLM 空 = 用对话模型）
        rerank_cfg = await ChatService._get_rerank_cfg(db, user, agent)
        tools = ToolRegistry.build_langchain_tools(
            db, user, agent.tools, citations_store=citations_store,
            enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg,
            debug_store=debug_store)
        pending_events: list[dict] = []

        async def event_sink(event: dict) -> None:
            """工具事件收集（SSE 转发由 _invoke_agent_stream 的 pending_events 处理）"""
            pending_events.append(event)

        tools_desc = ChatService._business_tools_desc(agent)
        tools = tools + ChatService._build_builtin_tools(
            db, user, agent, llm_cfg, tools_desc, event_sink=event_sink)
        async for event in ChatService._invoke_agent_stream(
                db, user, agent, llm_cfg, conv, tools=tools,
                user_content=request.message, citations_store=citations_store,
                pending_events=pending_events):
            if event.get("type") == "delta":
                full_answer.append(event["content"])
            yield event
        # 工具事件兑底 drain（astream 结束后可能仍有未转发事件）
        while pending_events:
            yield pending_events.pop(0)
        citations.extend(citations_store)
        if debug_store is not None:
            yield {"type": "debug", "debug": debug_store}
        yield {"type": "citations",
               "citations": [c.model_dump(mode="json") for c in citations_store]}
        yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # simple（零工具直接回答，意图路由开启时）
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _chat_simple(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        conv: object,
        request: ChatRequest,
        debug_store: dict | None = None,
    ) -> tuple[str, list[Citation]]:
        """simple 档：零工具直接回答（LLMService 调用 + checkpoint 手动读写）

        历史纯文本化（过滤 tool_calls/ToolMessage，防 API 400）+ 最近检索残留注入。
        """
        messages = await ChatService._build_simple_messages(
            agent, conv, request.message)
        answer = await ChatService._invoke_llm_direct(
            llm_cfg, agent, conv, messages)
        await ChatService._persist_simple_turn(conv.id, request.message, answer)
        return answer, []

    @staticmethod
    async def _chat_simple_stream(
        db: AsyncSession,
        user: Users,
        agent: object,
        llm_cfg: object,
        conv: object,
        request: ChatRequest,
        full_answer: list[str],
        citations: list[Citation],
        debug_store: dict | None = None,
    ) -> AsyncIterator[dict]:
        """simple 档流式：LLMService.chat_stream 逐段产出 delta"""
        from backend.services.llm import LLMService

        messages = await ChatService._build_simple_messages(
            agent, conv, request.message)
        temperature = (agent.temperature if agent.temperature is not None
                       else getattr(llm_cfg, "temperature", None))
        if temperature is None:
            temperature = 0.7
        top_p = (agent.top_p if agent.top_p is not None
                 else getattr(llm_cfg, "top_p", None))
        if top_p is None:
            top_p = 0.9
        try:
            async for delta in LLMService.chat_stream(
                    provider=llm_cfg.provider,
                    model_name=llm_cfg.model_name,
                    api_key=llm_cfg.api_key,
                    base_url=llm_cfg.base_url,
                    messages=messages,
                    temperature=temperature,
                    top_p=top_p,
                    protocol=getattr(llm_cfg, "protocol", None)):
                full_answer.append(delta)
                yield {"type": "delta", "content": delta}
            await ChatService._persist_simple_turn(
                conv.id, request.message, "".join(full_answer))
        except Exception as e:
            if ChatService._is_temperature_error(e):
                yield {"type": "error", "code": 400,
                       "message": (
                           f"模型 {llm_cfg.model_name} 仅支持 temperature=1（推理模型），"
                           f"当前 Agent 配置为 {getattr(agent, 'temperature', '?')}"
                       ),
                       "suggestion": {"action": "set_temperature", "value": 1.0}}
            else:
                logger.error(f"simple 档流式调用失败: {e}")
                yield {"type": "error", "code": 502,
                       "message": f"LLM 服务调用失败: {e}"}
            yield {"type": "done"}

    @staticmethod
    async def _build_simple_messages(agent: object, conv: object,
                                     message: str) -> list[dict]:
        """simple 档消息组装：纯文本历史 + 最近检索残留注入 + 当前问题"""
        from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

        from backend.core.checkpointer import get_checkpointer

        cp = await get_checkpointer()
        tup = await cp.aget_tuple(ChatService._thread_config(conv))
        history: list[dict] = []
        residual = ""
        if tup is not None:
            msgs = list(tup.checkpoint.get("channel_values", {}).get("messages", []))
            text_msgs: list = []
            for m in msgs:
                if isinstance(m, ToolMessage):
                    residual = m.content or ""  # 覆盖式：保留最近一条检索内容
                elif isinstance(m, HumanMessage):
                    text_msgs.append(m)
                elif isinstance(m, AIMessage) and not m.tool_calls:
                    text_msgs.append(m)
            limit = settings.intent.simple_history_limit
            text_msgs = text_msgs[-limit:] if limit > 0 else text_msgs
            history = [
                {"role": "user" if isinstance(m, HumanMessage) else "assistant",
                 "content": m.content or ""}
                for m in text_msgs
            ]
        # 检索残留注入（最近一轮工具检索内容，供追问场景参考）
        sys_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        user_content = message
        if residual and settings.intent.simple_context_max_chars > 0:
            user_content = (
                f"以下是历史检索过的资料：\n{residual[:settings.intent.simple_context_max_chars]}"
                f"\n\n当前问题：{message}"
            )
            sys_prompt += "\n\n注意：参考资料可能与当前问题无关，请以对话历史为准。"
        return [{"role": "system", "content": sys_prompt}, *history,
                {"role": "user", "content": user_content}]

    @staticmethod
    async def _invoke_llm_direct(llm_cfg: object, agent: object,
                                 conv: object, messages: list[dict]) -> str:
        """simple 档直接 LLM 调用（采样参数优先级与 general 一致：Agent > 模型配置 > 默认 0.7/0.9）"""
        import time as _time

        from backend.services.llm import LLMService

        temperature = (agent.temperature if agent.temperature is not None
                       else getattr(llm_cfg, "temperature", None))
        if temperature is None:
            temperature = 0.7
        top_p = (agent.top_p if agent.top_p is not None
                 else getattr(llm_cfg, "top_p", None))
        if top_p is None:
            top_p = 0.9
        max_tokens = (agent.max_tokens if agent.max_tokens is not None
                      else getattr(llm_cfg, "max_tokens", None))
        t0 = _time.perf_counter()
        try:
            answer = await LLMService.chat(
                provider=llm_cfg.provider,
                model_name=llm_cfg.model_name,
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                messages=messages,
                temperature=temperature,
                top_p=top_p,
                protocol=getattr(llm_cfg, "protocol", None),
                max_tokens=max_tokens if max_tokens else None,
            )
            _llm_logger.info(
                "agent=%s type=simple conversation=%s duration_ms=%d error=None",
                getattr(agent, "name", "?"), str(conv.id),
                int((_time.perf_counter() - t0) * 1000))
            return answer
        except Exception as e:
            if ChatService._is_temperature_error(e):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": (
                            f"模型 {llm_cfg.model_name} 仅支持 temperature=1（推理模型），"
                            f"当前 Agent 配置为 {getattr(agent, 'temperature', '?')}"
                        ),
                        "suggestion": {"action": "set_temperature", "value": 1.0},
                    },
                )
            _llm_logger.error(
                "agent=%s type=simple duration_ms=%d error=%s",
                getattr(agent, "name", "?"),
                int((_time.perf_counter() - t0) * 1000), e)
            logger.error(f"simple 档 LLM 调用失败: {e}")
            raise HTTPException(status_code=502, detail=f"LLM 服务调用失败: {e}")

    @staticmethod
    async def _persist_simple_turn(conversation_id: UUID,
                                   user_message: str,
                                   assistant_message: str) -> None:
        """simple 档把 user + assistant 消息追加写入 checkpoint（版本号递增）

        与 _persist_turn_without_llm 同机制；simple 档不走 create_agent，
        需手动写回保证下一轮（simple 或 general）能读到本轮对话。
        """
        from datetime import datetime, timezone
        from uuid import uuid4

        from langchain_core.messages import AIMessage, HumanMessage
        from langgraph.checkpoint.base import Checkpoint

        from backend.core.checkpointer import get_checkpointer

        cp = await get_checkpointer()
        config = {"configurable": {"thread_id": str(conversation_id),
                                   "checkpoint_ns": ""}}
        tup = await cp.aget_tuple(config)
        if tup is None:
            checkpoint = Checkpoint(
                v=1,
                ts=datetime.now(timezone.utc).isoformat(),
                id=str(uuid4()),
                channel_values={"messages": []},
                channel_versions={"messages": "1"},
                versions_seen={},
                pending_sends=[],
            )
            metadata: dict = {}
            new_versions: dict = {"messages": "1"}
        else:
            checkpoint = tup.checkpoint
            metadata = tup.metadata or {}
            new_versions = dict(checkpoint.get("channel_versions", {}))
        messages = list(checkpoint.get("channel_values", {}).get("messages", []))
        messages.append(HumanMessage(content=user_message))
        messages.append(AIMessage(content=assistant_message))
        checkpoint["channel_values"]["messages"] = messages
        # blob 同版本 DO NOTHING，必须递增版本号
        cur_ver = str(new_versions.get("messages", "0"))
        new_versions["messages"] = (
            str(int(cur_ver) + 1) if cur_ver.isdigit()
            else f"{cur_ver}.{datetime.now(timezone.utc).timestamp()}")
        await cp.aput(config, checkpoint, metadata, new_versions)

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
    async def _get_enhance_cfg(db: AsyncSession, user: Users, agent: object):
        """增强 LLM 配置(MQE/HyDE 用):agent.enhance_llm_config_id → user_model_config

        空/失效/归属不符 → None（RAGTool 收到 None 时跳过增强，跟随对话模型）
        """
        if not getattr(agent, "enhance_llm_config_id", None):
            return None
        cfg = await UserModelConfigRepo.get_by_id(db, agent.enhance_llm_config_id)
        if cfg is None or cfg.user_id != user.id or cfg.model_type != 2:
            return None  # 配置失效时静默回退（无增强）
        return cfg

    @staticmethod
    async def _get_rerank_cfg(db: AsyncSession, user: Users, agent: object):
        """Rerank 模型配置:agent.rerank_config_id → user_model_config(model_type=3)

        空/失效/归属不符 → None（RAGTool 收到 None 时用 tools.rerank 全局默认）
        """
        if not getattr(agent, "rerank_config_id", None):
            return None
        cfg = await UserModelConfigRepo.get_by_id(db, agent.rerank_config_id)
        if cfg is None or cfg.user_id != user.id or cfg.model_type != 3:
            return None  # 配置失效时静默回退到全局默认
        return cfg

    @staticmethod
    async def _classify_intent(agent: object, llm_cfg: object,
                               message: str) -> str:
        """general Agent 意图判定：simple / general（路由关闭时恒为 general）"""
        from backend.services.intent import IntentService

        return await IntentService.classify(
            agent, llm_cfg, message, ChatService._business_tools_desc(agent))

    @staticmethod
    def _business_tools_desc(agent: object) -> str:
        """业务工具描述列表（供意图分类 / plan 工具参考）"""
        from backend.tools import ToolRegistry

        lines = []
        for tool in (agent.tools or []):
            try:
                cls = ToolRegistry._get(tool.get("type"))
            except Exception:
                continue
            lines.append(f"- {cls.type}: {cls.description}")
        return "\n".join(lines) or "（无业务工具）"

    @staticmethod
    def _build_builtin_tools(db: AsyncSession, user: Users, agent: object,
                             llm_cfg: object, tools_desc: str,
                             event_sink=None) -> list:
        """内置推理工具（plan/reflect，按 Agent 开关注册）"""
        from backend.tools import PlanTool, ReflectTool

        result = []
        if getattr(agent, "plan_enabled", True):
            result.append(PlanTool.build_langchain(
                db, user, {}, llm_cfg=llm_cfg, tools_desc=tools_desc,
                event_sink=event_sink))
        if getattr(agent, "reflect_enabled", True):
            result.append(ReflectTool.build_langchain(
                db, user, {}, llm_cfg=llm_cfg, event_sink=event_sink))
        return result

    @staticmethod
    async def _build_agent(db: AsyncSession, user: Users, agent: object,
                           llm_cfg: object, tools: list) -> object:
        """构建 create_agent(带 checkpointer + middleware)

        采样参数优先级（Phase 4.8）：Agent 配置 > 模型配置 > 默认（0.7 / 0.9）
        延迟 import langchain 系（启动提速：仅首次对话时才加载）。
        """
        from langchain.agents import create_agent
        from langchain_openai import ChatOpenAI

        from backend.core.checkpointer import get_checkpointer

        summary_cfg = await ChatService._get_summary_cfg(db, user, agent)
        middlewares = build_middlewares(summary_cfg, llm_cfg)
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        cp = await get_checkpointer()
        temperature = (agent.temperature if agent.temperature is not None
                       else getattr(llm_cfg, "temperature", None))
        if temperature is None:
            temperature = 0.7
        top_p = (agent.top_p if agent.top_p is not None
                 else getattr(llm_cfg, "top_p", None))
        if top_p is None:
            top_p = 0.9
        max_tokens = (agent.max_tokens if agent.max_tokens is not None
                      else getattr(llm_cfg, "max_tokens", None))
        return create_agent(
            model=ChatOpenAI(
                model=llm_cfg.model_name, api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url or "https://api.openai.com/v1",
                temperature=temperature, top_p=top_p,
                max_tokens=max_tokens if max_tokens else None, timeout=60.0),
            tools=tools, system_prompt=system_prompt,
            checkpointer=cp, middleware=middlewares)

    @staticmethod
    def _thread_config(conv: object) -> dict:
        """checkpoint thread 配置(thread_id = conversation_id)"""
        return {"configurable": {"thread_id": str(conv.id), "checkpoint_ns": ""}}

    @staticmethod
    async def _repair_checkpoint(conv: object) -> None:
        """对话前修复 checkpoint 消息序列:孤立 tool_calls 补 ToolMessage(防 LLM 400)

        场景:流式对话被中断(abort)时,LangGraph 可能已写入带 tool_calls 的
        AIMessage 但未写入 ToolMessage,下次对话 OpenAI 兼容 API 会报
        "assistant message with tool_calls must be followed by tool messages"。

        注意:checkpoint_blobs 按 (thread_id, checkpoint_ns, channel, version)
        UNIQUE 且 DO NOTHING(同版本不可变),因此修复后必须递增 messages
        的版本号,否则新内容不会落库。
        """
        from backend.core.checkpointer import get_checkpointer

        cp = await get_checkpointer()
        config = ChatService._thread_config(conv)
        tup = await cp.aget_tuple(config)
        if tup is None:
            return
        msgs = list(tup.checkpoint.get("channel_values", {}).get("messages", []))
        fixed = ChatService._repair_messages(msgs)
        if len(fixed) != len(msgs):
            # 递增 messages 版本号(blob 同版本 DO NOTHING,必须换新版本)
            cur_ver = str(tup.checkpoint.get("channel_versions", {}).get("messages", "0"))
            new_ver = (str(int(cur_ver) + 1) if cur_ver.isdigit()
                       else f"{cur_ver}.{datetime.now(timezone.utc).timestamp()}")
            tup.checkpoint["channel_versions"]["messages"] = new_ver
            tup.checkpoint["channel_values"]["messages"] = fixed
            await cp.aput(config, tup.checkpoint, tup.metadata or {},
                          {"messages": new_ver})

    @staticmethod
    def _repair_messages(msgs: list) -> list:
        """清洗消息列表:assistant 的 tool_calls 后缺失对应 ToolMessage 时自动补齐

        返回:修复后的新列表(无断裂时不新增元素)
        """
        from langchain_core.messages import ToolMessage

        result = list(msgs)
        inserted = 0  # 已插入数量(修正后续插入位置)
        for i, m in enumerate(list(result)):
            if not (hasattr(m, "tool_calls") and m.tool_calls):
                continue
            for tc in m.tool_calls:
                tc_id = tc.get("id") or tc.get("tool_call_id")
                if not tc_id:
                    continue
                # 向后查找该 tool_call_id 的 ToolMessage
                has = any(
                    isinstance(x, ToolMessage) and x.tool_call_id == tc_id
                    for x in result[i + 1 + inserted:])
                if not has:
                    result.insert(
                        i + 1 + inserted,
                        ToolMessage(
                            content="工具调用已被中断，未执行。请直接回答用户或重新调用工具。",
                            tool_call_id=tc_id,
                            name=tc.get("name") or "tool",
                        ),
                    )
                    inserted += 1
        return result

    @staticmethod
    def _is_temperature_error(e: Exception) -> bool:
        """判断是否为推理模型的 temperature 限制错误（仅允许 temperature=1）"""
        msg = str(e).lower()
        return "temperature" in msg and ("only 1" in msg or "not allowed" in msg)

    @staticmethod
    async def _invoke_agent(db: AsyncSession, user: Users, agent: object,
                            llm_cfg: object, conv: object, tools: list,
                            user_content: str,
                            citations_store: list | None = None) -> str:
        """非流式:create_agent.ainvoke(thread_id = conversation_id)（埋点：耗时/错误）

        推理模型（Kimi K3 / o1 等）仅支持 temperature=1：检测到 temperature 限制错误时
        自动以 temperature=1 降级重试一次（不落库）。
        """
        import time as _time

        from langchain_core.messages import HumanMessage

        await ChatService._repair_checkpoint(conv)
        lc_agent = await ChatService._build_agent(db, user, agent, llm_cfg, tools)
        t0 = _time.perf_counter()
        try:
            result = await lc_agent.ainvoke(
                {"messages": [HumanMessage(content=user_content)]},
                config=ChatService._thread_config(conv))
            _llm_logger.info(
                "agent=%s type=%s conversation=%s duration_ms=%d error=None",
                getattr(agent, "name", "?"), getattr(agent, "type", "?"),
                str(conv.id), int((_time.perf_counter() - t0) * 1000))
            return result["messages"][-1].content or ""
        except Exception as e:
            # 推理模型 temperature 限制 → 结构化错误（前端弹窗让用户确认：改温度重试 / 换模型）
            if ChatService._is_temperature_error(e):
                raise HTTPException(
                    status_code=400,
                    detail={
                        "message": (
                            f"模型 {llm_cfg.model_name} 仅支持 temperature=1（推理模型），"
                            f"当前 Agent 配置为 {getattr(agent, 'temperature', '?')}"
                        ),
                        "suggestion": {"action": "set_temperature", "value": 1.0},
                    },
                )
            _llm_logger.error(
                "agent=%s type=%s conversation=%s duration_ms=%d error=%s",
                getattr(agent, "name", "?"), getattr(agent, "type", "?"),
                str(conv.id), int((_time.perf_counter() - t0) * 1000), e)
            logger.error(f"Agent 调用失败: {e}")
            raise HTTPException(status_code=502, detail=f"LLM 服务调用失败: {e}")

    @staticmethod
    async def _invoke_agent_stream(db: AsyncSession, user: Users, agent: object,
                                   llm_cfg: object, conv: object, tools: list,
                                   user_content: str,
                                   citations_store: list | None = None,
                                   pending_events: list[dict] | None = None
                                   ) -> AsyncIterator[dict]:
        """流式:create_agent.astream(stream_mode='messages',工具轮自动跳过)（埋点：耗时/错误）

        pending_events: 工具事件队列（plan/reflect 执行时由 event_sink 收集，
        本方法在每个 chunk 前转发，保证 SSE 事件与文本流顺序正确）。

        推理模型仅支持 temperature=1：检测到 temperature 限制错误时
        自动以 temperature=1 降级重试一次（不落库）。
        """
        import time as _time

        from langchain_core.messages import AIMessageChunk, HumanMessage

        await ChatService._repair_checkpoint(conv)
        lc_agent = await ChatService._build_agent(db, user, agent, llm_cfg, tools)
        t0 = _time.perf_counter()
        try:
            async for chunk, _meta in lc_agent.astream(
                    {"messages": [HumanMessage(content=user_content)]},
                    config=ChatService._thread_config(conv),
                    stream_mode="messages"):
                # 工具事件转发（plan/reflect 执行时由 event_sink 收集）
                if pending_events is not None:
                    while pending_events:
                        yield pending_events.pop(0)
                if isinstance(chunk, AIMessageChunk) and chunk.content:
                    yield {"type": "delta", "content": chunk.content}
            _llm_logger.info(
                "agent=%s type=%s conversation=%s duration_ms=%d error=None",
                getattr(agent, "name", "?"), getattr(agent, "type", "?"),
                str(conv.id), int((_time.perf_counter() - t0) * 1000))
        except Exception as e:
            # 推理模型 temperature 限制 → 结构化 error 事件（前端弹窗让用户确认）
            if ChatService._is_temperature_error(e):
                yield {"type": "error", "code": 400,
                       "message": (
                           f"模型 {llm_cfg.model_name} 仅支持 temperature=1（推理模型），"
                           f"当前 Agent 配置为 {getattr(agent, 'temperature', '?')}"
                       ),
                       "suggestion": {"action": "set_temperature", "value": 1.0}}
                yield {"type": "done"}
                return
            _llm_logger.error(
                "agent=%s type=%s conversation=%s duration_ms=%d error=%s",
                getattr(agent, "name", "?"), getattr(agent, "type", "?"),
                str(conv.id), int((_time.perf_counter() - t0) * 1000), e)
            logger.error(f"Agent 流式调用失败: {e}")
            yield {"type": "error", "code": 502,
                   "message": f"LLM 服务调用失败: {e}"}
            yield {"type": "done"}

    # ═══════════════════════════════════════════════
    # 内部工具
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _load_context(db: AsyncSession, user: Users, agent_id: UUID,
                            conversation_id: UUID | None,
                            client_id: str | None = None,
                            exec_user: Users | None = None):
        """定位 Agent + 校验 LLM 配置 + 获取/创建会话（支持匿名 client_id / 执行身份）"""
        atype, agent, llm_cfg = await ChatService._load_agent_context(
            db, user, agent_id, exec_user)
        conv = await ChatService._get_or_create_conversation(
            db, user, agent_id, conversation_id, client_id, exec_user)
        return atype, agent, llm_cfg, conv

    @staticmethod
    async def _get_or_create_conversation(db: AsyncSession, user: Users,
                                          agent_id: UUID,
                                          conversation_id: UUID | None,
                                          client_id: str | None = None,
                                          exec_user: Users | None = None):
        """获取会话(校验归属 + Agent 匹配)或自动创建

        匿名场景：创建时 user_id 空 + client_id；获取时校验 conv.client_id 匹配。
        """
        if conversation_id is None:
            resp = await ConversationService.create(
                db, user, agent_id, client_id=client_id, exec_user=exec_user)
            return await ConversationRepo.get_by_id(db, resp.id)
        conv = await ConversationRepo.get_by_id(db, conversation_id)
        if conv is None or conv.status == 9:
            raise HTTPException(status_code=404, detail="会话不存在")
        if client_id:
            if conv.client_id != client_id:
                raise HTTPException(status_code=404, detail="会话不存在")
        elif conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        if conv.agent_id != agent_id:
            raise HTTPException(status_code=400, detail="会话与 Agent 不匹配")
        return conv

    @staticmethod
    async def _load_agent_context(db: AsyncSession, user: Users,
                                  agent_id: UUID,
                                  exec_user: Users | None = None) -> tuple[str, object, object]:
        """
        定位 Agent(索引表 → 类型表)并校验 LLM 配置

        exec_user:公开接口登录场景传入 Agent 所有者，归属校验用它；
        user 仅用于会话归属。
        返回 (type, agent_orm, llm_cfg)
        Raises: HTTPException 404/400
        """
        check_user = exec_user or user
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is None or entry.status == 9 or entry.user_id != check_user.id:
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
        if llm_cfg is None or llm_cfg.user_id != check_user.id or llm_cfg.model_type != 2:
            raise HTTPException(status_code=400, detail="LLM 模型配置无效")
        if not llm_cfg.api_key:
            raise HTTPException(status_code=400, detail="LLM 配置缺少 API Key")

        return atype, agent, llm_cfg

    @staticmethod
    async def _persist_turn_without_llm(conversation_id: UUID,
                                        user_message: str) -> None:
        """无命中短路:把 user + assistant 消息手动写入 checkpoint"""
        from langchain_core.messages import AIMessage, HumanMessage

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
                channel_versions={"messages": "1"},
                versions_seen={},
                pending_sends=[],
            )
            messages: list = []
            metadata: dict = {}
            new_versions: dict = {"messages": "1"}
        else:
            checkpoint = tup.checkpoint
            messages = list(checkpoint.get("channel_values", {}).get("messages", []))
            metadata = tup.metadata or {}
            new_versions = checkpoint.get("channel_versions", {})

        messages.append(HumanMessage(content=user_message))
        messages.append(AIMessage(content="知识库中没有相关信息。"))
        checkpoint["channel_values"]["messages"] = messages
        await cp.aput(config, checkpoint, metadata, new_versions)

    @staticmethod
    async def _persist_messages(db: AsyncSession, conv: object,
                                user_msg: str, assistant_msg: str,
                                citations: list[Citation]) -> None:
        """原子追加本轮消息到会话 JSON（user + assistant 含引用）

        一轮两条一次 append_messages（单条 UPDATE || 拼接，数据库内部读-拼-写，
        并发安全且成对写入）。首轮对话自动命名:会话标题仍为默认值时,
        用当次首条用户消息前 10 字更新(仅用第一条消息,不取后续消息;超过 10 字末尾加省略号)
        """
        from backend.services.conversation import DEFAULT_CONV_TITLE

        if conv.title is None or conv.title == DEFAULT_CONV_TITLE:
            title = user_msg if len(user_msg) <= 10 else user_msg[:10] + "..."
            await ConversationRepo.update_title(db, conv, title)
        now = datetime.now(timezone.utc).isoformat()
        await MessageRepo.append_messages(db, conv.id, [
            {"role": "user", "content": user_msg, "citations": None,
             "created_at": now},
            {"role": "assistant", "content": assistant_msg,
             "citations": [c.model_dump(mode="json") for c in citations]
             if citations else None,
             "created_at": now},
        ])
        await db.commit()
        # 清理旧 checkpoint：仅保留最近 keep_rounds 轮（阈值 config.yaml checkpoint.keep_rounds）
        # 旧快照无人读取且含全量历史(O(N²) 死数据)；清理失败不阻断主流程
        try:
            from backend.core.checkpointer import prune_checkpoints
            from backend.core.config import settings
            keep = getattr(settings.checkpoint, "keep_rounds", 5)
            if keep > 0:
                await prune_checkpoints(conv.id, keep)
        except Exception:
            logger.exception("checkpoint 清理失败")

    @staticmethod
    def _build_user_prompt(citations: list[Citation], message: str) -> str:
        """组装带引用块的 user prompt(simple_rag 用)：模板常量 + 引用块 join"""
        blocks = "\n\n".join(
            f"[{i}] （来源：《{c.document_name}》）\n{c.content}"
            for i, c in enumerate(citations, 1)
        )
        # 空引用时 blocks 为空串，join 时过滤，避免多出空白行
        parts = [_RAG_PROMPT_HEADER, blocks, _RAG_PROMPT_FOOTER, f"用户问题：{message}"]
        return "\n\n".join(p for p in parts if p)
