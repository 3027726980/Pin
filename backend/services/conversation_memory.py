"""会话消息状态适配：通过 LangGraph 公开接口管理快照，不拼装 checkpoint。"""
import asyncio
from weakref import WeakValueDictionary

from langchain.agents.middleware.types import AgentState
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.graph import END, START, StateGraph
from langgraph.types import Overwrite

from backend.core.checkpointer import get_checkpointer
from backend.core.observability.preparation import preparation_stage

_locks = WeakValueDictionary()


class ConversationMemoryService:
    """复用主 Agent 消息 schema，以公开图状态 API 读写，旧 thread 按需迁移。"""

    @staticmethod
    def config(conversation_id):
        """返回与主 Agent 相同的 thread/namespace 配置。"""
        return {"configurable": {"thread_id": f"memory_v2:{conversation_id}", "checkpoint_ns": ""}}

    @staticmethod
    def legacy_config(conversation_id):
        """旧版本 thread 配置，仅用于兼容读取及删除。"""
        return {"configurable": {"thread_id": str(conversation_id), "checkpoint_ns": ""}}

    @staticmethod
    def lock(conversation_id):
        """串行化本进程内的记忆更新，弱引用避免闲置会话锁永久累积。"""
        key = str(conversation_id)
        lock = _locks.get(key)
        if lock is None:
            lock = asyncio.Lock()
            _locks[key] = lock
        return lock

    @staticmethod
    async def graph():
        """构造消息状态适配图；不执行模型、工具或外部请求。"""
        def identity(state):
            """状态更新占位节点，仅为公开 aupdate_state 提供写入节点。"""
            return {}

        graph = StateGraph(AgentState)
        graph.add_node("model", identity)
        graph.add_node("tools", identity)
        graph.add_edge(START, "model")
        graph.add_edge("model", END)
        graph.add_edge("tools", END)
        return graph.compile(checkpointer=await get_checkpointer())

    @staticmethod
    async def ensure(conversation_id, graph):
        """无新快照时，通过图接口迁移旧消息；避开手写版本与框架版本混用。"""
        config = ConversationMemoryService.config(conversation_id)
        snapshot = await graph.aget_state(config)
        if snapshot.created_at is None:
            legacy = await graph.aget_state(ConversationMemoryService.legacy_config(conversation_id))
            if legacy.created_at is not None:
                messages = list(legacy.values.get("messages", []))
                with preparation_stage("checkpoint_migration", "迁移旧会话消息到框架管理状态", message_count=len(messages)):
                    await graph.aupdate_state(config, {"messages": messages}, as_node="model")
                snapshot = await graph.aget_state(config)
        return snapshot

    @staticmethod
    async def messages(conversation_id):
        """通过图快照读取最新消息，不读取或修改 checkpoint 内部字典。"""
        async with ConversationMemoryService.lock(conversation_id):
            graph = await ConversationMemoryService.graph()
            with preparation_stage("checkpoint_read", "读取会话图状态"):
                snapshot = await ConversationMemoryService.ensure(conversation_id, graph)
        return list(snapshot.values.get("messages", []))

    @staticmethod
    async def append_turn(conversation_id, user_message, assistant_message):
        """追加成对消息，版本和 metadata 全部由图状态更新负责。"""
        async with ConversationMemoryService.lock(conversation_id):
            graph = await ConversationMemoryService.graph()
            await ConversationMemoryService.ensure(conversation_id, graph)
            await graph.aupdate_state(ConversationMemoryService.config(conversation_id), {
                "messages": [HumanMessage(content=user_message), AIMessage(content=assistant_message)],
            }, as_node="model")

    @staticmethod
    async def repair(conversation_id, repair_messages):
        """对最新消息执行修复，仅有变化时通过 Overwrite 更新，防止 reducer 重复追加。"""
        async with ConversationMemoryService.lock(conversation_id):
            graph = await ConversationMemoryService.graph()
            config = ConversationMemoryService.config(conversation_id)
            with preparation_stage("checkpoint_read", "读取会话图状态"):
                snapshot = await ConversationMemoryService.ensure(conversation_id, graph)
            messages = list(snapshot.values.get("messages", []))
            with preparation_stage("checkpoint_validate", "校验消息与工具结果", message_count=len(messages)):
                fixed = repair_messages(messages)
            if fixed != messages:
                with preparation_stage("checkpoint_write", "通过图状态接口保存修复"):
                    await graph.aupdate_state(config, {"messages": Overwrite(fixed)}, as_node="model")
            return len(messages), fixed != messages
