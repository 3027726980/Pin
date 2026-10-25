"""作者：LHF；时间：2026-10-25；作用：按回答模型容量压缩会话，自动和手动共用。"""

from langchain.agents.middleware import SummarizationMiddleware
from datetime import UTC, datetime
from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.utils.function_calling import convert_to_openai_tool

from backend.core.config import settings
from backend.core.observability.model_context import write_context_event
from backend.core.observability.operations import model_call_scope
from backend.services.model_policy import current_turn_budget
from backend.services.context_tokens import ContextTokenCounter
from backend.services.model_metadata import fetch_model_capacity


def count_context_tokens(messages, model_name=""):
    """使用模型对应的 tiktoken 分词器计数，未知模型使用明确的编码回退。"""
    return ContextTokenCounter(model_name)(messages)


async def resolve_model_capacity(llm_cfg, model=None):
    """作用：优先使用供应商 /models 容量，缺失或请求失败时沿用显式配置/profile/回退。"""
    capacity = await fetch_model_capacity(llm_cfg)
    return (capacity, "provider_models_api") if capacity else resolve_input_capacity(llm_cfg, model)


def resolve_input_capacity(llm_cfg, model=None):
    """优先按模型名显式覆盖，再读回答模型 profile，缺失时用可配置回退容量。"""
    sc = settings.checkpoint.summarization
    limits = getattr(sc, "model_input_limits", None)
    explicit = getattr(limits, llm_cfg.model_name, None) if limits else None
    profile = getattr(model, "profile", None) or {}
    if explicit is not None:
        capacity, source = explicit, "configuration"
    elif profile.get("max_input_tokens"):
        capacity, source = profile["max_input_tokens"], "answer_model_profile"
    else:
        capacity, source = getattr(sc, "fallback_max_input_tokens", 32768), "configured_fallback"
    if isinstance(capacity, bool) or int(capacity) < 256:
        raise ValueError("模型最大输入容量必须至少为 256 token")
    return int(capacity), source


class ContextSummarizationMiddleware(SummarizationMiddleware):
    """用回答模型容量解释 fraction，保留框架安全切分与消息 reducer。"""

    def __init__(self, summary_model, capacity, capacity_source, *, answer_model_name=""):
        """构建摘要中间件；回答容量与实际执行总结的模型分别管理。"""
        sc = settings.checkpoint.summarization
        self.input_capacity = capacity
        self.capacity_source = capacity_source
        self.overhead_tokens = 0
        self.request_system = None
        self.request_tools = None
        self.reference_provider = None
        self.context_counter = ContextTokenCounter(answer_model_name)
        trigger = float(getattr(sc, "trigger_fraction", 0.8))
        keep = float(getattr(sc, "keep_fraction", 0.2))
        if not 0 < keep < trigger < 1:
            raise ValueError("压缩比例必须满足 0 < keep_fraction < trigger_fraction < 1")
        super().__init__(model=summary_model, trigger=("fraction", trigger),
                         keep=("fraction", keep), token_counter=self.context_counter,
                         trim_tokens_to_summarize=None)

    def _get_profile_limits(self):
        """框架 fraction 扩展点：始终返回回答模型容量，避免误用总结模型。"""
        return self.input_capacity

    def configure_request(self, system_prompt, tools):
        """计入系统提示词与工具 Schema 的固定开销，调用前由 Agent 工厂设置。"""
        schemas = [convert_to_openai_tool(tool) for tool in tools]
        self.request_system = SystemMessage(content=system_prompt)
        self.request_tools = schemas
        self.overhead_tokens = self.context_counter([SystemMessage(content=system_prompt)], tools=schemas)

    def _should_summarize(self, messages, total_tokens):
        """自动触发按消息加系统/工具开销计算；摘要与保留部分仍只修改消息。"""
        request_tokens = total_tokens + self.overhead_tokens
        if self.request_system is not None:
            projected = list(messages)
            reference = self.reference_provider() if self.reference_provider else ""
            if reference:
                for index in range(len(projected) - 1, -1, -1):
                    if isinstance(projected[index], HumanMessage):
                        original = projected[index]
                        projected[index] = original.model_copy(update={"content": original.text + reference})
                        break
            request_tokens = self.context_counter([self.request_system, *projected], tools=self.request_tools)
        return request_tokens >= self.input_capacity * self.trigger[1]

    async def _acreate_summary(self, messages_to_summarize):
        """分批覆盖全部待总结内容，失败抛出异常，禁止错误文本覆盖记忆。"""
        from langchain_core.messages import get_buffer_string

        # 分块只发生在总结输入中；持久化工具协议消息仍由框架整体切分。
        text = get_buffer_string(messages_to_summarize, format="xml")
        chunk_tokens = int(getattr(settings.checkpoint.summarization, "summary_chunk_tokens", 12000))
        if chunk_tokens < 256:
            raise ValueError("summary_chunk_tokens 必须至少为 256")
        summary_profile = getattr(self.model, "profile", None) or {}
        summary_limit = int(summary_profile.get("max_input_tokens") or 8192)
        summary_counter = ContextTokenCounter(getattr(self.model, "model_name", ""))
        prompt_overhead = summary_counter([HumanMessage(content=self.summary_prompt.format(messages=""))])
        chunk_tokens = min(chunk_tokens, max(256, summary_limit - prompt_overhead - 1024))
        partials = []
        for chunk in summary_counter.split_text(text, chunk_tokens):
            budget = current_turn_budget()
            if budget is not None:
                budget.acquire_llm()
            with model_call_scope("summary"):
                response = await self.model.ainvoke(
                    self.summary_prompt.format(messages=chunk),
                    config={"metadata": {"lc_source": "summarization"}})
            summary = response.text.strip()
            if not summary or summary.startswith("Error generating summary:"):
                raise RuntimeError("总结模型未返回有效摘要，原会话记忆已保留")
            partials.append(summary)
        if not partials:
            raise RuntimeError("没有可总结的消息")
        # 结构化合并各段摘要，不再次裁掉最早内容；过大时交由下方压缩收益检查拒绝写入。
        return "\n\n".join(f"片段 {i + 1}：{value}" for i, value in enumerate(partials)) if len(partials) > 1 else partials[0]

    async def compact(self, messages, *, force=False):
        """生成压缩后的新消息列表；无收益或失败时不替换原始状态。"""
        before = self.context_counter(messages)
        detail = {"started_at": datetime.now(UTC).isoformat(), "trigger": "manual" if force else "fraction",
                  "trigger_fraction": self.trigger[1], "keep_fraction": self.keep[1],
                  "input_capacity": self.input_capacity, "capacity_source": self.capacity_source,
                  "overhead_tokens": self.overhead_tokens, "before_tokens": before,
                  "before_messages": len(messages), "token_count_method": self.context_counter.method,
                  "token_encoding": self.context_counter.encoding.name,
                  "token_encoding_source": self.context_counter.source}
        if len(messages) < 2 or (not force and not self._should_summarize(messages, before)):
            return messages, False
        cutoff = self._determine_cutoff_index(messages)
        if force and cutoff <= 0:
            # 手动请求在未到自动阈值时仍总结旧轮，保留最近一次完整用户交互。
            humans = [i for i, msg in enumerate(messages) if isinstance(msg, HumanMessage)
                      and msg.additional_kwargs.get("lc_source") != "summarization"]
            cutoff = self._find_safe_cutoff_point(messages, humans[-1]) if humans else 0
        if cutoff <= 0:
            return messages, False
        try:
            summary = await self._acreate_summary(messages[:cutoff])
            result = [*self._build_new_messages(summary), *messages[cutoff:]]
            after = self.context_counter(result)
            if after >= before:
                write_context_event("context.compaction", "摘要未缩小上下文，保留原记忆",
                                    {**detail, "after_tokens": after, "compressed": False}, status="degraded")
                return messages, False
        except Exception:
            write_context_event("context.compaction", "压缩失败，保留原会话记忆", detail, status="failed")
            raise
        write_context_event("context.compaction", "会话上下文已压缩", {
            **detail, "after_tokens": after, "after_messages": len(result), "compressed": True})
        return result, True

    async def abefore_model(self, state, runtime):
        """每次模型调用前压缩，使用公开 Overwrite 更新消息状态。"""
        from langgraph.types import Overwrite

        messages, compressed = await self.compact(list(state["messages"]))
        return {"messages": Overwrite(messages)} if compressed else None
