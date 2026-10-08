"""
对话编排服务:按 Agent 类型分发对话(记忆由 checkpoint 持久化)

- 所有类型统一 create_agent + checkpointer(thread_id = conversation_id)
- simple_rag:每轮首次模型调用强制选择 RAG 工具，命中/无命中均走 Agent 自动保存
- general:LLM 自主决策工具调用(LangGraph 多轮)
- 每轮对话原子追加到会话 JSON(user 原始问题 + assistant 回答含 citations)
- 短期记忆:SummarizationMiddleware(参数走 config.yaml,总结模型 Agent 级配置)
"""
import asyncio
import logging
import sys
import time
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
from backend.schemas.agent import ChatRequest, ChatResponse, Citation, CitationBinding
from backend.services.citation_bindings import (
    build_citation_bindings,
    strip_unbound_source_markers,
)
from backend.services.conversation import ConversationService
from backend.services.conversation_memory import ConversationMemoryService
from backend.services.middleware import build_middlewares
from backend.tools import ToolRegistry
from backend.core.config import settings
from backend.core.observability.events import diagnostic_preview
from backend.core.observability.preparation import bind_preparation_sink, preparation_stage

logger = logging.getLogger(__name__)
_llm_logger = logging.getLogger("backend.llm")  # 链路日志：LLM 调用（写 llm.log）

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
        include_debug: bool = True,
    ) -> ChatResponse:
        """消费统一 Turn 事件流并聚合为兼容的非流式响应。

        client_id 非空 = 匿名访客场景（会话归属 client_id，user 为 Agent 所有者）；
        为空 = 登录用户场景（会话归属 user.id）。
        exec_user:公开接口登录场景的 Agent 所有者（agent/LLM 校验身份，会话仍归 user）。
        """
        answer_parts: list[str] = []
        citations: list[Citation] = []
        bindings: list[CitationBinding] = []
        debug_store: dict = {}
        conversation_id: UUID | None = request.conversation_id
        trace_id: str | None = None
        async for event in ChatService.chat_stream(
                db, user, agent_id, request,
                client_id=client_id, exec_user=exec_user):
            trace_id = event.trace_id
            if event.conversation_id:
                conversation_id = UUID(event.conversation_id)
            if event.type == "answer.delta" and event.content:
                answer_parts.append(event.content)
            elif event.type == "citations.completed":
                citations = [
                    Citation.model_validate(item) for item in event.citations or []
                ]
                bindings = [
                    CitationBinding.model_validate(item)
                    for item in event.detail.get("bindings", [])
                ]
            elif event.visibility.value == "debug":
                debug_store[event.stage_id] = event.detail
            elif event.type == "turn.failed":
                status_code = (
                    int(event.code) if (event.code or "").isdigit() else 502
                )
                raise HTTPException(
                    status_code=status_code,
                    detail=event.summary or "请求失败",
                )
            elif event.type == "turn.cancelled":
                raise HTTPException(status_code=499, detail="请求已取消")

        if conversation_id is None:
            raise RuntimeError("Turn stream completed without conversation_id")
        return ChatResponse(
            conversation_id=conversation_id,
            answer="".join(answer_parts),
            citations=citations,
            citation_bindings=bindings,
            debug=debug_store if include_debug else None,
            trace_id=trace_id,
        )

    @staticmethod
    async def chat_stream(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
        client_id: str | None = None,
        exec_user: Users | None = None,
        request_id: str | None = None,
    ) -> AsyncIterator["AgentEvent"]:
        """执行唯一 Turn 流，并返回 AgentEvent v2。"""
        from backend.services.turn_stream import execute_turn_stream

        runner = ChatService._chat_stream_legacy(
            db, user, agent_id, request,
            client_id=client_id, exec_user=exec_user)
        async for event in execute_turn_stream(
                request_id=request_id or f"req_{uuid4().hex}",
                agent_id=agent_id,
                conversation_id=request.conversation_id,
                runner=runner):
            yield event

    @staticmethod
    async def _chat_stream_legacy(
        db: AsyncSession,
        user: Users,
        agent_id: UUID,
        request: ChatRequest,
        client_id: str | None = None,
        exec_user: Users | None = None,
    ) -> AsyncIterator[dict]:
        """内部领域 runner；产生兼容事件但不负责 v2 Turn 终态。

        client_id 非空 = 匿名访客场景（会话归属 client_id）；
        exec_user:公开接口登录场景的 Agent 所有者。
        """
        atype, agent, llm_cfg, conv = await ChatService._load_context(
            db, user, agent_id, request.conversation_id, client_id, exec_user)
        yield {"type": "context", "conversation_id": str(conv.id)}
        full_answer: list[str] = []
        citations: list[Citation] = []
        stream_failed = False
        # 后端始终采集安全调试数据；前端 Debug 仅控制展示。
        debug_store: dict = {}
        try:
            if atype == "simple_rag":
                async for event in ChatService._chat_simple_rag_stream(
                        db, user, agent, llm_cfg, conv, request,
                        full_answer, citations, debug_store=debug_store):
                    if event.get("type") not in {"debug", "citations", "done"}:
                        if event.get("type") == "error":
                            stream_failed = True
                        yield event
            else:
                from backend.services.agent_graph import AgentGraphService

                history = await ChatService._load_semantic_history(conv, limit=5)

                async def simple_stream_runner() -> AsyncIterator[dict]:
                    async for event in ChatService._chat_simple_stream(
                            db, user, agent, llm_cfg, conv, request,
                            full_answer, citations, debug_store=debug_store):
                        if event.get("type") not in {"citations", "done"}:
                            yield event

                async def main_stream_runner(guidance: str) -> AsyncIterator[dict]:
                    async for event in ChatService._chat_general_stream(
                            db, user, agent, llm_cfg, conv, request,
                            full_answer, citations, debug_store=debug_store,
                            orchestration_guidance=guidance):
                        if event.get("type") not in {"debug", "citations", "done"}:
                            yield event

                async def draft_runner(guidance: str) -> str:
                    return await ChatService._generate_review_draft(
                        agent, llm_cfg, conv, request.message, history, guidance)

                async for event in AgentGraphService.stream(
                        agent=agent, llm_cfg=llm_cfg, message=request.message,
                        history=history, tools_desc=ChatService._business_tools_desc(agent),
                        simple_stream_runner=simple_stream_runner,
                        main_stream_runner=main_stream_runner,
                        draft_runner=draft_runner):
                    if event.get("type") == "answer.revision_started":
                        full_answer.clear()
                    elif event.get("type") == "delta" and not full_answer:
                        # revision delta 由图节点直接产生，不经过 main_stream_runner。
                        full_answer.append(str(event.get("content", "")))
                    if event.get("type") == "intent" and debug_store is not None:
                        debug_store["intent"] = event.get("intent")
                        debug_store["intent_code"] = event.get("intent_code")
                    if event.get("type") == "error":
                        stream_failed = True
                    yield event
            source_map = ChatService._source_map(citations)
            sanitized_answer = strip_unbound_source_markers(
                "".join(full_answer), ChatService._bindable_source_ids(source_map))
            full_answer[:] = [sanitized_answer]
            if debug_store is not None:
                yield {"type": "debug", "debug": debug_store}
            yield ChatService._citation_event(sanitized_answer, citations)
            yield {"type": "done"}
        finally:
            source_map = ChatService._source_map(citations)
            sanitized_answer = strip_unbound_source_markers(
                "".join(full_answer), ChatService._bindable_source_ids(source_map))
            if not stream_failed:
                await ChatService._persist_messages(
                    db, conv, request.message, sanitized_answer, citations,
                    build_citation_bindings(sanitized_answer, source_map))

    # ═══════════════════════════════════════════════
    # simple_rag：RAG 工具由 Agent 执行并自动保存
    # ═══════════════════════════════════════════════

    @staticmethod
    def _rag_tool_configs(agent: object) -> list[dict]:
        """把 simple_rag 的绑定字段转换为现有工具配置，保留增强与精排参数。"""
        config = {"type": "rag", "kb_id": str(agent.kb_id)}
        for key in ("top_k", "score_threshold", "mqe_enabled", "hyde_enabled",
                    "mqe_mode", "hyde_mode", "mqe_query_count", "rerank_enabled", "rerank_mode"):
            config[key] = getattr(agent, key, None)
        return [config]

    @staticmethod
    async def _chat_simple_rag(db, user, agent, llm_cfg, conv, request,
                               debug_store=None) -> tuple[str, list[Citation]]:
        """注册 RAG 工具进入 Agent；命中和无命中均由框架保存。"""
        return await ChatService._chat_general(
            db, user, agent, llm_cfg, conv, request, debug_store=debug_store,
            tool_configs=ChatService._rag_tool_configs(agent))

    @staticmethod
    async def _chat_simple_rag_stream(db, user, agent, llm_cfg, conv, request,
                                      full_answer, citations, debug_store=None) -> AsyncIterator[dict]:
        """复用 Agent 工具事件、流式回答及引用收集，不在 Service 提前检索。"""
        async for event in ChatService._chat_general_stream(
            db, user, agent, llm_cfg, conv, request, full_answer, citations,
            debug_store=debug_store, tool_configs=ChatService._rag_tool_configs(agent)):
            yield event

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
        orchestration_guidance: str = "",
        tool_configs: list[dict] | None = None,
    ) -> tuple[str, list[Citation]]:
        """general:最终主 Agent 节点执行业务工具（计划/反思不再注册为工具）。"""
        citations_store: list[Citation] = []
        enhance_cfg = await ChatService._get_enhance_cfg(db, user, agent)
        if enhance_cfg is None:
            enhance_cfg = llm_cfg  # 跟随对话模型（设计：增强 LLM 空 = 用对话模型）
        rerank_cfg = await ChatService._get_rerank_cfg(db, user, agent)
        tools = ToolRegistry.build_langchain_tools(
            db, user, tool_configs if tool_configs is not None else agent.tools, citations_store=citations_store,
            enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg,
            debug_store=debug_store)
        answer = await ChatService._invoke_agent(
            db, user, agent, llm_cfg, conv, tools=tools,
            user_content=request.message, citations_store=citations_store,
            orchestration_guidance=orchestration_guidance)
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
        orchestration_guidance: str = "",
        tool_configs: list[dict] | None = None,
    ) -> AsyncIterator[dict]:
        """general 流式：仅注册业务工具，计划/反思由外层 LangGraph 节点负责。"""
        citations_store: list[Citation] = []
        enhance_cfg = await ChatService._get_enhance_cfg(db, user, agent)
        if enhance_cfg is None:
            enhance_cfg = llm_cfg  # 跟随对话模型（设计：增强 LLM 空 = 用对话模型）
        rerank_cfg = await ChatService._get_rerank_cfg(db, user, agent)
        event_queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        async def event_sink(event: dict) -> None:
            await event_queue.put(("event", event))

        tools = ToolRegistry.build_langchain_tools(
            db, user, tool_configs if tool_configs is not None else agent.tools, citations_store=citations_store,
            enhance_cfg=enhance_cfg, rerank_cfg=rerank_cfg,
            debug_store=debug_store, event_sink=event_sink)
        answer_perf = time.perf_counter()
        yield {"type": "stage", "stage": "agent", "stage_id": "agent.1",
               "status": "running", "summary": "Agent 正在处理", "visibility": "public"}
        async for event in ChatService._invoke_agent_stream(
                db, user, agent, llm_cfg, conv, tools=tools,
                user_content=request.message, citations_store=citations_store,
                orchestration_guidance=orchestration_guidance,
                event_queue=event_queue):
            if event.get("type") == "delta":
                full_answer.append(event["content"])
            yield event
        yield {"type": "stage", "stage": "agent", "stage_id": "agent.1",
               "status": "completed", "summary": "Agent 处理完成", "visibility": "public",
               "duration_ms": round((time.perf_counter() - answer_perf) * 1000)}
        citations.extend(citations_store)
        if debug_store is not None:
            yield {"type": "debug", "debug": debug_store}
        yield ChatService._citation_event("".join(full_answer), citations_store)
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
        """轻量直答也执行零工具 Agent，由框架自动保存原始问答。"""
        answer = await ChatService._invoke_agent(
            db, user, agent, llm_cfg, conv, [], request.message, lightweight=True)
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
        """轻量直答复用 Agent 流式执行、错误处理和链路埋点。"""
        async for event in ChatService._invoke_agent_stream(
            db, user, agent, llm_cfg, conv, [], request.message, lightweight=True):
            if event.get("type") == "delta":
                full_answer.append(event["content"])
            yield event

    @staticmethod
    async def _generate_review_draft(agent: object, llm_cfg: object, conv: object,
                                     message: str, history: list[dict[str, str]],
                                     orchestration_guidance: str) -> str:
        """生成仅供反思节点审查的临时草稿，不写 checkpoint 且不执行业务工具。"""
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        if orchestration_guidance:
            system_prompt = f"{system_prompt}\n\n{orchestration_guidance}"
        system_prompt += (
            "\n\n你正在生成供内部审查的答案草稿。只回答当前用户问题，"
            "不要描述计划、反思或内部编排过程。"
        )
        messages = [
            {"role": "system", "content": system_prompt},
            *history[-5:],
            {"role": "user", "content": message},
        ]
        return await ChatService._invoke_llm_direct(llm_cfg, agent, conv, messages)

    @staticmethod
    async def _invoke_llm_direct(llm_cfg: object, agent: object,
                                 conv: object, messages: list[dict]) -> str:
        """simple 档直接 LLM 调用（采样参数优先级与 general 一致：Agent > 模型配置 > 默认 0.7/0.9）"""
        import time as _time

        from backend.services.llm import LLMService

        from backend.services.model_policy import build_model_invocation_config

        invocation = build_model_invocation_config(llm_cfg, agent=agent)
        t0 = _time.perf_counter()
        try:
            answer = await LLMService.chat(
                provider=invocation.provider,
                model_name=invocation.model_name,
                api_key=invocation.api_key,
                base_url=invocation.base_url,
                messages=messages,
                temperature=invocation.temperature,
                top_p=invocation.top_p,
                protocol=invocation.protocol,
                timeout=invocation.timeout,
                max_tokens=invocation.max_tokens,
                purpose="answer",
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
            raise HTTPException(
                status_code=ChatService._upstream_error_status(e),
                detail=f"LLM 服务调用失败: {e}")

    @staticmethod
    async def _persist_simple_turn(conversation_id: UUID,
                                   user_message: str,
                                   assistant_message: str) -> None:
        """轻量直答通过统一图状态接口保存成对消息，框架维护版本与 metadata。"""
        await ConversationMemoryService.append_turn(conversation_id, user_message, assistant_message)

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
    async def _load_semantic_history(conv: object, limit: int = 5) -> list[dict[str, str]]:
        """从 checkpoint 读取最近语义消息，排除 tool_calls/ToolMessage 后供意图节点使用。"""
        from langchain_core.messages import AIMessage, HumanMessage

        messages = await ConversationMemoryService.messages(conv.id)
        semantic: list[dict[str, str]] = []
        for item in messages:
            if isinstance(item, HumanMessage):
                semantic.append({"role": "user", "content": item.content or ""})
            elif isinstance(item, AIMessage) and not item.tool_calls:
                semantic.append({"role": "assistant", "content": item.content or ""})
        return semantic[-limit:]

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
    async def _build_agent(db: AsyncSession, user: Users, agent: object,
                           llm_cfg: object, tools: list,
                           orchestration_guidance: str = "", lightweight: bool = False) -> object:
        """构建 create_agent(带 checkpointer + middleware)

        采样参数优先级（Phase 4.8）：Agent 配置 > 模型配置 > 默认（0.7 / 0.9）
        延迟 import langchain 系（启动提速：仅首次对话时才加载）。
        """
        with preparation_stage("dependencies", "加载 Agent 依赖",
                               first_import="langchain.agents" not in sys.modules,
                               openai_first_import="langchain_openai" not in sys.modules):
            from langchain.agents import create_agent
            from langchain_openai import ChatOpenAI

        from backend.core.checkpointer import get_checkpointer

        with preparation_stage("summary_config", "读取总结模型配置"):
            summary_cfg = await ChatService._get_summary_cfg(db, user, agent)
        with preparation_stage("middleware", "构建 Agent 中间件"):
            middlewares = build_middlewares(summary_cfg, llm_cfg)
            if lightweight:
                from backend.services.simple_context import SimpleContextMiddleware
                middlewares.append(SimpleContextMiddleware())
            elif tools and hasattr(agent, "kb_id"):
                from backend.services.rag_context import RagFirstMiddleware
                middlewares.append(RagFirstMiddleware())
        system_prompt = agent.system_prompt.replace("{agent_name}", agent.name)
        if tools and hasattr(agent, "kb_id"):
            system_prompt += (
                '\n\n每轮必须先检索知识库，再基于本轮工具返回的资料回答。'
                '引用必须使用结果中的 [S#] 来源标签。检索结果为空或资料不足时，'
                '明确说明“知识库中没有相关信息”，不得用历史资料冒充本轮命中。'
            )
        if orchestration_guidance:
            system_prompt = f"{system_prompt}\n\n{orchestration_guidance}"
        with preparation_stage("checkpointer", "获取 checkpoint 管理器"):
            cp = await get_checkpointer()
        from backend.services.llm import get_rate_limiter
        from backend.services.model_policy import build_model_invocation_config

        invocation = build_model_invocation_config(llm_cfg, agent=agent)
        with preparation_stage("model_client", "初始化模型客户端", model=invocation.model_name):
            model = ChatOpenAI(
                model=invocation.model_name, api_key=invocation.api_key,
                base_url=invocation.base_url or "https://api.openai.com/v1",
                temperature=invocation.temperature, top_p=invocation.top_p,
                max_tokens=invocation.max_tokens, timeout=invocation.timeout,
                max_retries=invocation.max_retries,
                rate_limiter=get_rate_limiter(
                    invocation.provider, invocation.model_name,
                    invocation.api_key))
        with preparation_stage("graph", "构建 Agent 执行图", tool_count=len(tools)):
            return create_agent(model=model, tools=tools, system_prompt=system_prompt,
                                checkpointer=cp, middleware=middlewares)

    @staticmethod
    def _thread_config(conv: object) -> dict:
        """checkpoint thread 配置(thread_id = conversation_id)"""
        return ConversationMemoryService.config(conv.id)

    @staticmethod
    def _upstream_error_status(error: Exception) -> int:
        """把上游限流识别为 429，其余调用错误维持 502。"""
        message = str(error).lower()
        status_code = getattr(error, "status_code", None)
        return 429 if status_code == 429 or "rate_limit" in message or "429" in message else 502

    @staticmethod
    async def _repair_checkpoint(conv: object) -> None:
        """对话前通过图状态接口修复孤立工具结果，不修改 checkpoint 内部结构。"""
        with preparation_stage("checkpoint_repair_state", "读取并校验会话状态"):
            await ConversationMemoryService.repair(conv.id, ChatService._repair_messages)

    @staticmethod
    def _repair_messages(msgs: list) -> list:
        """清洗消息列表:assistant 的 tool_calls 后缺失对应 ToolMessage 时自动补齐

        同时清理历史 AI 消息中的展示型 ``[S#]``，避免下一轮模型复制
        已失去当前来源上下文的引用编号。

        返回:修复后的新列表(无断裂且无来源标记时不新增元素)
        """
        from langchain_core.messages import AIMessage, ToolMessage

        result = []
        for message in msgs:
            if isinstance(message, AIMessage) and isinstance(message.content, str):
                sanitized = strip_unbound_source_markers(message.content)
                if sanitized != message.content:
                    message = message.model_copy(update={"content": sanitized})
            result.append(message)
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
                            content="工具调用已被中断，执行结果未知。不要假定未执行或自动重试有副作用的操作。",
                            tool_call_id=tc_id,
                            name=tc.get("name") or "tool",
                            status="error",
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
                            citations_store: list | None = None,
                            orchestration_guidance: str = "", lightweight: bool = False) -> str:
        """非流式:create_agent.ainvoke(thread_id = conversation_id)（埋点：耗时/错误）

        推理模型（Kimi K3 / o1 等）仅支持 temperature=1：检测到 temperature 限制错误时
        自动以 temperature=1 降级重试一次（不落库）。
        """
        import time as _time

        from langchain_core.messages import HumanMessage

        with preparation_stage("total", "Agent 执行准备"):
            with preparation_stage("checkpoint_repair", "检查并修复会话 checkpoint"):
                await ChatService._repair_checkpoint(conv)
            lc_agent = await ChatService._build_agent(
                db, user, agent, llm_cfg, tools, orchestration_guidance,
                **({"lightweight": True} if lightweight else {}))
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
            raise HTTPException(
                status_code=ChatService._upstream_error_status(e),
                detail=f"LLM 服务调用失败: {e}")

    @staticmethod
    async def _invoke_agent_stream(db: AsyncSession, user: Users, agent: object,
                                   llm_cfg: object, conv: object, tools: list,
                                   user_content: str,
                                   citations_store: list | None = None,
                                   pending_events: list[dict] | None = None,
                                   orchestration_guidance: str = "",
                                   event_queue: asyncio.Queue[tuple[str, object]] | None = None,
                                   lightweight: bool = False,
                                   ) -> AsyncIterator[dict]:
        """同时消费消息与节点更新，实时展示模型轮、工具选择和执行状态。

        ``pending_events`` 仅保留为旧调用方兼容；规划和反思已迁移到 AgentGraph 节点，
        不再作为主 Agent 工具事件。

        推理模型仅支持 temperature=1：检测到 temperature 限制错误时
        自动以 temperature=1 降级重试一次（不落库）。
        """
        import time as _time

        from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage, ToolMessage

        preparation_events = asyncio.Queue()

        async def prepare():
            """保持准备事件与原始异常顺序，并给整段准备计时。"""
            with bind_preparation_sink(preparation_events.put_nowait):
                with preparation_stage("total", "Agent 执行准备"):
                    with preparation_stage("checkpoint_repair", "检查并修复会话 checkpoint"):
                        await ChatService._repair_checkpoint(conv)
                    return await ChatService._build_agent(
                        db, user, agent, llm_cfg, tools, orchestration_guidance,
                **({"lightweight": True} if lightweight else {}))

        preparation_task = asyncio.create_task(prepare())
        try:
            while not preparation_task.done() or not preparation_events.empty():
                if not preparation_events.empty():
                    yield preparation_events.get_nowait()
                else:
                    await asyncio.wait({preparation_task}, timeout=0.02)
            lc_agent = await preparation_task
        finally:
            if not preparation_task.done():
                preparation_task.cancel()
            await asyncio.gather(preparation_task, return_exceptions=True)
        t0 = _time.perf_counter()
        try:
            async def chunks():
                """模型 Token 与节点更新并行消费，工具选择不等待最终答案。"""
                round_number = 1
                model_started = _time.perf_counter()
                model_open = True
                first_model_token_ms: int | None = None
                announced_tools: set[str] = set()
                tool_starts: dict[str, float] = {}
                tool_names: dict[str, str] = {}

                async def observed_stream():
                    """记录未捕获异常并收口失败阶段，保留原异常供上层处理。"""
                    try:
                        async for item in lc_agent.astream(
                                {"messages": [HumanMessage(content=user_content)]},
                                config=ChatService._thread_config(conv),
                                stream_mode=["messages", "updates"]):
                            yield item
                    except Exception as error:
                        logger.exception("Agent 执行异常 conversation=%s active_tools=%s", conv.id, tool_names)
                        for call_id, begin in list(tool_starts.items()):
                            yield "updates", {"diagnostic_failure": {
                                "type": "stage", "stage": "tool", "stage_id": f"tool.{call_id}",
                                "status": "failed", "visibility": "debug", "code": "TOOL_EXECUTION_FAILED",
                                "duration_ms": round((_time.perf_counter() - begin) * 1000),
                                "summary": f"工具执行中断：{tool_names.get(call_id, 'tool')}",
                                "detail": {"tool": tool_names.get(call_id), "tool_call_id": call_id,
                                           "error_type": type(error).__name__, **diagnostic_preview(str(error))},
                            }}
                        if model_open:
                            yield "updates", {"diagnostic_failure": {
                                **model_event("failed"), "visibility": "debug", "code": "MODEL_EXECUTION_FAILED",
                                "detail": {"model": llm_cfg.model_name, "error_type": type(error).__name__,
                                           **diagnostic_preview(str(error))},
                            }}
                        raise

                def model_event(status: str) -> dict:
                    return {
                        "type": "stage", "stage": "model", "stage_id": f"model.{round_number}",
                        "status": status, "visibility": "public",
                        "summary": (f"第 {round_number} 次模型调用：等待输出（含供应商排队）"
                                    if status == "running" else f"第 {round_number} 次模型调用完成"),
                        "duration_ms": None if status == "running" else round((_time.perf_counter() - model_started) * 1000),
                        "detail": {"model": llm_cfg.model_name, "first_token_ms": first_model_token_ms},
                    }

                yield model_event("running"), None
                async for mode, item in observed_stream():
                    if mode == "messages":
                        chunk, metadata = item
                        if metadata.get("langgraph_node") not in {None, "model"}:
                            continue
                        if first_model_token_ms is None and (getattr(chunk, "content", None) or getattr(chunk, "tool_call_chunks", None)):
                            first_model_token_ms = round((_time.perf_counter() - model_started) * 1000)
                            yield {"type": "stage", "stage": "model", "stage_id": f"model.{round_number}",
                                   "status": "running", "progress": True,
                                   "summary": f"第 {round_number} 次模型调用已开始输出",
                                   "detail": {"model": llm_cfg.model_name, "first_token_ms": first_model_token_ms}}, None
                        for call in getattr(chunk, "tool_call_chunks", []) or []:
                            name = call.get("name")
                            if name and name not in announced_tools:
                                announced_tools.add(name)
                                yield {"type": "stage", "stage": "model", "stage_id": f"model.{round_number}",
                                       "status": "running", "progress": True,
                                       "summary": f"模型正在选择工具：{name}",
                                       "detail": {"model": llm_cfg.model_name, "tool": name, "first_token_ms": first_model_token_ms}}, None
                        yield chunk, metadata
                        continue
                    if mode != "updates" or not isinstance(item, dict):
                        continue
                    for node, update in item.items():
                        if node == "diagnostic_failure":
                            yield update, None
                            continue
                        if not isinstance(update, dict) or node not in {"model", "tools"}:
                            continue
                        for msg in update.get("messages", []):
                            if isinstance(msg, AIMessage) and model_open:
                                yield model_event("completed"), None
                                # 只保存可见正文与工具调用，不保存 additional_kwargs 中的隐藏推理。
                                visible = msg.content if isinstance(msg.content, str) else [
                                    block for block in msg.content if isinstance(block, str)
                                    or isinstance(block, dict) and block.get("type") == "text"]
                                yield {"type": "stage", "stage": "model_output", "stage_id": f"model.{round_number}.output",
                                       "status": "completed", "visibility": "debug", "duration_ms": 0,
                                       "summary": f"第 {round_number} 次模型输出",
                                       "detail": {"model": llm_cfg.model_name, **diagnostic_preview(visible),
                                                  "tool_calls": diagnostic_preview(msg.tool_calls), "usage": msg.usage_metadata}}, None
                                model_open = False
                                for call in msg.tool_calls:
                                    call_id = str(call.get("id") or uuid4().hex)
                                    tool_starts[call_id] = _time.perf_counter()
                                    tool_names[call_id] = call["name"]
                                    yield {"type": "stage", "stage": "tool", "stage_id": f"tool.{call_id}",
                                           "status": "running", "visibility": "public",
                                           "summary": f"正在调用工具：{call['name']}",
                                           "detail": {"tool": call["name"]}}, None
                                    yield {"type": "stage", "stage": "tool", "stage_id": f"tool.{call_id}.params",
                                           "status": "completed", "visibility": "debug", "duration_ms": 0,
                                           "summary": f"工具参数：{call['name']}",
                                           "detail": {"tool": call["name"], "tool_call_id": call_id,
                                                      "args": diagnostic_preview(call.get("args", {}))}}, None
                            elif isinstance(msg, ToolMessage):
                                begin = tool_starts.pop(msg.tool_call_id, _time.perf_counter())
                                failed = getattr(msg, "status", None) == "error"
                                tool_names.pop(msg.tool_call_id, None)
                                yield {"type": "stage", "stage": "tool", "stage_id": f"tool.{msg.tool_call_id}",
                                       "status": "degraded" if failed else "completed", "visibility": "public",
                                       "summary": f"工具{'执行失败，交由 Agent 处理' if failed else '已返回结果'}：{msg.name or 'tool'}",
                                       "duration_ms": round((_time.perf_counter() - begin) * 1000),
                                       "detail": {"tool": msg.name or "tool", "content_length": len(str(msg.content))}}, None
                                yield {"type": "stage", "stage": "tool", "stage_id": f"tool.{msg.tool_call_id}.output",
                                       "status": "degraded" if failed else "completed", "visibility": "debug", "duration_ms": 0,
                                       "summary": f"工具{'错误详情' if failed else '返回内容'}：{msg.name or 'tool'}",
                                       "detail": {"tool": msg.name, "tool_call_id": msg.tool_call_id,
                                                  "is_error": failed, **diagnostic_preview(msg.content)}}, None
                        if node == "tools" and not tool_starts:
                            round_number += 1
                            model_started = _time.perf_counter()
                            model_open = True
                            first_model_token_ms = None
                            announced_tools.clear()
                            yield model_event("running"), None
                if model_open:
                    yield model_event("completed"), None

            if event_queue is None:
                stream = chunks()
            else:
                sentinel = object()

                async def produce() -> None:
                    try:
                        async for item in chunks():
                            await event_queue.put(("chunk", item))
                    finally:
                        await event_queue.put(("done", sentinel))

                producer = asyncio.create_task(produce())

                async def merged():
                    try:
                        while True:
                            kind, item = await event_queue.get()
                            if kind == "done":
                                break
                            if kind == "event":
                                yield item, None
                            else:
                                yield item
                        await producer
                    finally:
                        if not producer.done():
                            producer.cancel()
                        await asyncio.gather(producer, return_exceptions=True)

                stream = merged()

            async for chunk, _meta in stream:
                if isinstance(chunk, dict) and chunk.get("type"):
                    yield chunk
                    continue
                # 工具事件转发（plan/reflect 执行时由 event_sink 收集）
                if pending_events is not None:
                    while pending_events:
                        yield pending_events.pop(0)
                if isinstance(chunk, (AIMessage, AIMessageChunk)) and chunk.content:
                    content = chunk.content
                    if isinstance(content, list):
                        content = "".join(block if isinstance(block, str) else str(block.get("text", ""))
                                          for block in content if isinstance(block, str) or isinstance(block, dict) and block.get("type") == "text")
                    if content:
                        yield {"type": "delta", "content": content}
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
            yield {"type": "error", "code": ChatService._upstream_error_status(e),
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
    async def _persist_messages(db: AsyncSession, conv: object,
                                user_msg: str, assistant_msg: str,
                                citations: list[Citation],
                                citation_bindings: list[CitationBinding]) -> None:
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
             "citation_bindings": [b.model_dump(mode="json") for b in citation_bindings]
             if citation_bindings else None,
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
                await prune_checkpoints(ConversationMemoryService.config(conv.id)["configurable"]["thread_id"], keep)
        except Exception:
            logger.exception("checkpoint 清理失败")

    @staticmethod
    def _source_map(citations: list[Citation]) -> dict[str, Citation]:
        """从本轮候选引用创建 source_id 到 chunk 的唯一映射。"""
        return {
            citation.source_id: citation
            for citation in citations
            if citation.source_id is not None
        }

    @staticmethod
    def _bindable_source_ids(source_map: dict[str, Citation]) -> set[str]:
        """返回能够生成结构化引用绑定的本轮来源编号。"""
        return {
            source_id
            for source_id, citation in source_map.items()
            if citation.content.strip()
        }

    @staticmethod
    def _citation_event(answer: str, citations: list[Citation]) -> dict:
        """构造保留旧 citations 字段的 SSE 结构化 bindings 事件。"""
        bindings = build_citation_bindings(answer, ChatService._source_map(citations))
        return {
            "type": "citations",
            "bindings": [binding.model_dump(mode="json") for binding in bindings],
            "citations": [citation.model_dump(mode="json") for citation in citations],
        }
