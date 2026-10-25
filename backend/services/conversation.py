# 作者：LHF；时间：2026-10-25；作用：支持上下文比例压缩、手动压缩或模型输入日志。
"""会话业务:创建/列表/删除(软删 + 清理 checkpoint)"""
from uuid import UUID
from datetime import UTC, datetime

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import ConversationRepo, MessageRepo, AgentIndexRepo
from backend.schemas.conversation import ConversationResponse
from backend.services.citation_bindings import strip_unbound_source_markers

# 会话默认标题(首轮对话后自动用首条用户消息命名)
DEFAULT_CONV_TITLE = "新会话"

class ConversationService:
    """会话业务逻辑"""

    @staticmethod
    async def context_usage(db, user, conv_id, draft=None):
        """作者：LHF；2026-10-25；只读估算所属会话消息、系统及工具占用，不执行模型或迁移。"""
        from langchain_openai import ChatOpenAI
        from langchain_core.messages import SystemMessage
        from langchain_core.utils.function_calling import convert_to_openai_tool

        from backend.services.chat import ChatService
        from backend.services.context_compaction import resolve_model_capacity
        from backend.services.context_tokens import ContextTokenCounter
        from backend.services.conversation_memory import ConversationMemoryService
        from backend.tools import ToolRegistry

        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9 or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        _, agent, cfg = await ChatService._load_agent_context(db, user, conv.agent_id)
        capacity, source = await resolve_model_capacity(
            cfg, ChatOpenAI(model=cfg.model_name, api_key="profile-only"))
        configs = agent.tools
        tools = ToolRegistry.build_langchain_tools(db, user, configs, citations_store=[])
        tools = ChatService._with_skill_tools(db, user, agent, tools)
        prompt = ChatService._system_prompt(agent, tools)
        counter = ContextTokenCounter(cfg.model_name)
        schemas = [convert_to_openai_tool(tool) for tool in tools]
        # 仅读取最新完整快照；旧会话读取旧 thread，不触发 ensure 的迁移写入。
        async with ConversationMemoryService.lock(conv_id):
            graph = await ConversationMemoryService.graph()
            snapshot = await graph.aget_state(ConversationMemoryService.config(conv_id))
            if snapshot.created_at is None:
                snapshot = await graph.aget_state(ConversationMemoryService.legacy_config(conv_id))
        messages = list(snapshot.values.get("messages", []))
        if draft is not None:
            from langchain_core.messages import HumanMessage
            from backend.skills import SkillRegistry
            from backend.skills.runtime import available_skills, preference_text
            registry = SkillRegistry()
            available = {item["name"] for item in available_skills(registry, user.id, agent.id)}
            business = {tool.name for tool in tools} - {"load_skill", "read_skill_file", "run_skill_script"}
            bodies = {}
            for mention in draft.mentions:
                if mention.name not in (available if mention.kind == "skill" else business):
                    raise HTTPException(422, f"提及能力不可用：{mention.name}")
                if mention.kind == "skill":
                    bodies[mention.name] = registry.get(user.id, mention.name)["body"]
            if draft.message or draft.mentions:
                messages.append(HumanMessage(content=draft.message + preference_text(draft.mentions, bodies)))
        used = counter([SystemMessage(content=prompt), *messages], tools=schemas)
        return {"used_tokens": used, "input_capacity": capacity,
                "capacity_source": source, "model_name": cfg.model_name,
                "token_count_method": counter.method, "token_encoding": counter.encoding.name,
                "token_encoding_source": counter.source}

    @staticmethod
    async def compact(db, user, conv_id, *, client_id=None, exec_user=None, agent_id=None):
        """作者：LHF；2026-10-25；校验归属后手动压缩记忆，保留展示历史并返回 Trace。"""
        from uuid import uuid4

        # 延迟加载模型框架，避免普通会话列表/历史接口承担 Agent 依赖加载成本。
        from langchain_openai import ChatOpenAI
        from langgraph.types import Overwrite

        from backend.core.observability.context import TraceContext, bind_trace
        from backend.core.observability.model_context import write_context_event
        from backend.services.chat import ChatService
        from backend.services.context_compaction import (
            ContextSummarizationMiddleware,
            resolve_model_capacity,
        )
        from backend.services.conversation_memory import ConversationMemoryService
        from backend.services.middleware import _build_summary_model
        from backend.tools import ToolRegistry

        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9:
            raise HTTPException(status_code=404, detail="会话不存在")
        if (client_id and conv.client_id != client_id) or (not client_id and conv.user_id != user.id):
            raise HTTPException(status_code=404, detail="会话不存在")
        if agent_id is not None and conv.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="会话不存在")
        lock = ConversationMemoryService.turn_lock(conv_id)
        if lock.locked():
            raise HTTPException(status_code=409, detail="当前会话正在处理，请稍后压缩")
        trace = TraceContext.new(request_id=f"compact_{uuid4().hex}", conversation_id=conv_id, agent_id=conv.agent_id)
        compaction_started_at = datetime.now(UTC).isoformat()
        async with lock, bind_trace(trace):
            try:
                _, agent, cfg = await ChatService._load_agent_context(db, user, conv.agent_id, exec_user)
                actor = exec_user or user
                # 不执行 Agent 图，构建模型和工具仅用于容量及 Schema 计量。
                configs = agent.tools
                tools = ToolRegistry.build_langchain_tools(db, actor, configs, citations_store=[])
                tools = ChatService._with_skill_tools(db, actor, agent, tools)
                profile_model = ChatOpenAI(model=cfg.model_name, api_key="profile-only")
                summary_cfg = await ChatService._get_summary_cfg(db, actor, agent)
                middleware = ContextSummarizationMiddleware(
                    _build_summary_model(summary_cfg, cfg), *await resolve_model_capacity(cfg, profile_model),
                    answer_model_name=cfg.model_name)
                middleware.configure_request(ChatService._system_prompt(agent, tools), tools)
                async with ConversationMemoryService.lock(conv_id):
                    graph = await ConversationMemoryService.graph()
                    snapshot = await ConversationMemoryService.ensure(conv_id, graph)
                    before = ChatService._repair_messages(list(snapshot.values.get("messages", [])))
                    after, compressed = await middleware.compact(before, force=True)
                    if compressed:
                        await graph.aupdate_state(ConversationMemoryService.config(conv_id),
                                                  {"messages": Overwrite(after)}, as_node="model")
                result = {"compressed": compressed, "before_messages": len(before), "after_messages": len(after),
                          "before_tokens": middleware.context_counter(before), "after_tokens": middleware.context_counter(after),
                          "input_capacity": middleware.input_capacity, "capacity_source": middleware.capacity_source,
                          "trace_id": trace.trace_id}
                write_context_event("trace.summary", "手动压缩处理完成", {**result, "started_at": compaction_started_at})
                return result
            except Exception as error:
                write_context_event("trace.summary", "手动压缩失败，保留原会话记忆", {"started_at": compaction_started_at}, status="failed")
                if isinstance(error, HTTPException):
                    raise
                raise HTTPException(status_code=502, detail="上下文压缩失败，原会话记忆已保留") from error

    @staticmethod
    async def create(db: AsyncSession, user: Users, agent_id: UUID,
                     title: str | None = None,
                     client_id: str | None = None,
                     exec_user: Users | None = None) -> ConversationResponse:
        """创建会话;未传标题时使用默认标题'新会话',
        首轮对话后由 chat 服务用首条用户消息前 10 字自动命名

        匿名场景(client_id 非空):会话 user_id 存空 + client_id 标识访客;
        登录场景:user_id 归属用户。
        exec_user:公开接口登录场景的 Agent 所有者（用于归属校验，会话仍归 user）。
        """
        # 校验 Agent:存在 + 归属 + 未删除（exec_user 优先于 user 做归属校验）
        check_user = exec_user or user
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is None or entry.status == 9 or entry.user_id != check_user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")

        if title is None:
            title = DEFAULT_CONV_TITLE
        conv = await ConversationRepo.create(
            db, user_id=None if client_id else user.id,
            agent_id=agent_id, title=title, client_id=client_id)
        await db.commit()
        await db.refresh(conv)
        return ConversationResponse(
            id=conv.id, agent_id=conv.agent_id, title=conv.title,
            message_count=0, created_at=conv.created_at,
            updated_at=conv.updated_at)

    @staticmethod
    async def list_by_user(db: AsyncSession, user: Users,
                           agent_id: UUID | None, page: int,
                           page_size: int) -> tuple[list[dict], int]:
        """会话列表(补消息数)"""
        items, total = await ConversationRepo.list_by_user(
            db, user.id, page, page_size, agent_id)
        result = []
        for conv in items:
            mcount = await MessageRepo.count(db, conv.id)
            result.append(ConversationResponse(
                id=conv.id, agent_id=conv.agent_id, title=conv.title,
                message_count=mcount, created_at=conv.created_at,
                updated_at=conv.updated_at))
        return result, total

    @staticmethod
    async def list_by_client(db: AsyncSession, agent: object,
                             client_id: str, page: int,
                             page_size: int) -> tuple[list[dict], int]:
        """匿名访客会话列表(补消息数);先惰性清理超期匿名会话"""
        await ConversationRepo.purge_stale_anonymous(
            db, agent.id, agent.anonymous_retention_days)
        await db.commit()
        items, total = await ConversationRepo.list_by_client(
            db, client_id, page, page_size, agent.id)
        result = []
        for conv in items:
            mcount = await MessageRepo.count(db, conv.id)
            result.append(ConversationResponse(
                id=conv.id, agent_id=conv.agent_id, title=conv.title,
                message_count=mcount, created_at=conv.created_at,
                updated_at=conv.updated_at))
        return result, total

    @staticmethod
    async def get_messages(db: AsyncSession, user: Users, conv_id: UUID,
                           page: int, page_size: int,
                           client_id: str | None = None) -> tuple[list, int]:
        """历史消息(校验归属);匿名场景按 client_id 校验"""
        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9:
            raise HTTPException(status_code=404, detail="会话不存在")
        if client_id:
            if conv.client_id != client_id:
                raise HTTPException(status_code=404, detail="会话不存在")
        elif conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        msgs, total = await MessageRepo.list_by_conversation(
            db, conv_id, page, page_size)
        msgs = [
            {
                **message,
                "content": strip_unbound_source_markers(message.get("content") or ""),
            }
            if message.get("role") == "assistant"
            and not message.get("citations")
            and not message.get("citation_bindings")
            else message
            for message in msgs
        ]
        return msgs, total

    @staticmethod
    async def delete(db: AsyncSession, user: Users, conv_id: UUID,
                     client_id: str | None = None) -> None:
        """删除会话:软删 + 消息软删 + checkpoint 数据清理

        归属校验：匿名场景（client_id 非空）按 client_id；登录场景按 user_id
        （与 get_messages 一致，删不掉别人的会话）。
        """
        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9:
            raise HTTPException(status_code=404, detail="会话不存在")
        if client_id:
            if conv.client_id != client_id:
                raise HTTPException(status_code=404, detail="会话不存在")
        elif conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        await ConversationRepo.soft_delete(db, conv)
        await ConversationRepo.clear_messages(db, conv_id)
        await db.commit()

        # checkpoint 数据清理(独立连接)
        from backend.core.checkpointer import get_checkpointer

        cp = await get_checkpointer()
        from backend.services.conversation_memory import ConversationMemoryService
        await cp.adelete_thread(ConversationMemoryService.config(conv_id)["configurable"]["thread_id"])
        await cp.adelete_thread(str(conv_id))
