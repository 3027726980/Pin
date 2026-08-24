"""
Agent 工具：plan（任务规划）

内置推理工具（通用能力，非业务能力）：
- 不进入 agent.tools 配置，由 ChatService 按 plan_enabled 开关注册
- 用对话模型（llm_cfg）低温调用，为复杂任务生成分步执行计划
- 输出 JSON 步骤数组，作为建议性参考返回主 LLM（ReAct 循环自行决定执行方式）
- 执行成功时经 event_sink 推送 {"type": "plan", "plan": ...} 事件（SSE 展示）
- 失败返回错误 JSON，不阻断主循环

新增内置工具流程：tools/agent/ 建类 + ToolRegistry.TOOLS 注册 + ChatService 按开关构建。
"""
import json
import logging

from backend.core.config import settings
from backend.tools.common.base import BaseTool

logger = logging.getLogger(__name__)

PLAN_TOOL_DESCRIPTION = (
    "为复杂任务制定分步执行计划，明确每一步的目标与要调用的工具。"
    "适用于需要多步骤、多工具协作的复杂任务。"
)

_PLAN_PROMPT_TEMPLATE = (
    "你是一个任务规划助手。请为下面的任务制定分步执行计划。\n\n"
    "可用工具：\n{tools_desc}\n\n"
    "要求：\n"
    "- 只输出 JSON 数组，如 [{{\"step\": \"检索报销制度\", \"tool\": \"rag\", \"goal\": \"获取制度原文\"}}]\n"
    "- 每步的 tool 字段只能是可用工具名或 \"none\"（该步不需要工具时）\n"
    "- 步骤数量 2~8 步，覆盖任务的关键环节\n"
    "- 不要输出解释或 markdown 代码块标记\n\n"
    "任务：{task}"
)


class PlanTool(BaseTool):
    """规划工具：为复杂任务生成分步执行计划（建议性，供主 LLM 参考执行）"""

    type = "plan"
    description = PLAN_TOOL_DESCRIPTION
    name_ref_keys = {}

    @staticmethod
    async def validate_config(db, user, config: dict, **kwargs) -> None:
        """内置工具无需配置校验"""
        return None

    @staticmethod
    def build_langchain(db, user, config: dict, **kwargs):
        """构建 LangChain 工具（闭包绑定 llm_cfg / tools_desc / event_sink）

        额外参数（kwargs）:
            llm_cfg: 对话模型配置（规划调用用）
            tools_desc: 可用业务工具描述列表（注入规划 prompt）
            event_sink: async 回调，执行成功时推送 {"type": "plan", ...} 事件
        """
        from langchain_core.tools import tool

        llm_cfg = kwargs.get("llm_cfg")
        tools_desc = kwargs.get("tools_desc") or "（无业务工具）"
        event_sink = kwargs.get("event_sink")

        @tool
        async def plan(task: str) -> str:
            """为复杂任务制定分步执行计划，明确每一步的目标与要调用的工具。"""
            try:
                plan_text = await PlanTool._generate_plan(llm_cfg, task, tools_desc)
                if event_sink is not None:
                    await event_sink({"type": "plan", "plan": plan_text})
                return plan_text
            except Exception as e:
                logger.warning(f"plan 工具执行失败: {e}")
                return json.dumps({"error": f"规划失败: {e}"}, ensure_ascii=False)

        return plan

    @staticmethod
    async def _generate_plan(llm_cfg: object, task: str, tools_desc: str) -> str:
        """低温调用生成计划（推理模型 temperature 限制自动用 1 重试一次）"""
        from backend.services.llm import LLMService

        prompt = _PLAN_PROMPT_TEMPLATE.format(tools_desc=tools_desc, task=task)
        try:
            return await LLMService.chat(
                provider=llm_cfg.provider,
                model_name=llm_cfg.model_name,
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                messages=[{"role": "user", "content": prompt}],
                temperature=settings.intent.classify_temperature,
                top_p=0.9,
                protocol=getattr(llm_cfg, "protocol", None),
            )
        except Exception as e:
            from backend.services.chat import ChatService

            if ChatService._is_temperature_error(e):
                logger.warning("plan 模型仅支持 temperature=1，自动用 1 重试: %s", e)
                return await LLMService.chat(
                    provider=llm_cfg.provider,
                    model_name=llm_cfg.model_name,
                    api_key=llm_cfg.api_key,
                    base_url=llm_cfg.base_url,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=1.0,
                    top_p=0.9,
                    protocol=getattr(llm_cfg, "protocol", None),
                )
            raise
