"""
Agent 工具：reflect（答案反思）

内置推理工具（通用能力，非业务能力）：
- 不进入 agent.tools 配置，由 ChatService 按 reflect_enabled 开关注册
- 用对话模型（llm_cfg）低温调用，批评性审查答案草稿，输出改进建议
- 输出为 JSON 建议数组，主 LLM 据此修正最终回答
- 执行成功时经 event_sink 推送 {"type": "reflect", "suggestions": ...} 事件（SSE 展示）
- 失败返回错误 JSON，不阻断主循环
"""
import json
import logging

from backend.core.config import settings
from backend.tools.common.base import BaseTool

logger = logging.getLogger(__name__)

REFLECT_TOOL_DESCRIPTION = (
    "审查当前答案草稿，找出遗漏、错误或证据不足之处，给出具体改进建议。"
    "适用于生成最终答案前的质量检查。"
)

_REFLECT_PROMPT_TEMPLATE = (
    "你是一个答案审查助手。请批评性地审查下面的答案草稿，找出需要改进的地方。\n\n"
    "审查维度：\n"
    "1. 完整性：是否回答了用户问题的所有诉求\n"
    "2. 准确性：是否有事实错误或编造内容\n"
    "3. 证据充分性：结论是否有检索资料支撑（如有引用请核对）\n"
    "4. 表达：是否清晰、有条理\n\n"
    "要求：只输出 JSON 字符串数组（改进建议），如 [\"补充报销上限的具体数字\", \"引用制度原文标注来源\"]\n"
    "如果答案已完善，输出 []\n"
    "不要输出解释或 markdown 代码块标记。\n\n"
    "答案草稿：{draft}"
)


class ReflectTool(BaseTool):
    """反思工具：批评性审查答案草稿，输出改进建议（供主 LLM 修正最终回答）"""

    type = "reflect"
    description = REFLECT_TOOL_DESCRIPTION
    name_ref_keys = {}

    @staticmethod
    async def validate_config(db, user, config: dict, **kwargs) -> None:
        """内置工具无需配置校验"""
        return None

    @staticmethod
    def build_langchain(db, user, config: dict, **kwargs):
        """构建 LangChain 工具（闭包绑定 llm_cfg / event_sink）

        额外参数（kwargs）:
            llm_cfg: 对话模型配置（反思调用用）
            event_sink: async 回调，执行成功时推送 {"type": "reflect", ...} 事件
        """
        from langchain_core.tools import tool

        llm_cfg = kwargs.get("llm_cfg")
        event_sink = kwargs.get("event_sink")

        @tool
        async def reflect(draft: str) -> str:
            """审查答案草稿，找出遗漏、错误或证据不足之处，给出具体改进建议。"""
            try:
                suggestions = await ReflectTool._review_draft(llm_cfg, draft)
                if event_sink is not None:
                    await event_sink({"type": "reflect", "suggestions": suggestions})
                return suggestions
            except Exception as e:
                logger.warning(f"reflect 工具执行失败: {e}")
                return json.dumps({"error": f"反思失败: {e}"}, ensure_ascii=False)

        return reflect

    @staticmethod
    async def _review_draft(llm_cfg: object, draft: str) -> str:
        """低温调用生成反思建议（推理模型 temperature 限制自动用 1 重试一次）"""
        from backend.services.llm import LLMService

        prompt = _REFLECT_PROMPT_TEMPLATE.format(draft=draft)
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
                logger.warning("reflect 模型仅支持 temperature=1，自动用 1 重试: %s", e)
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
