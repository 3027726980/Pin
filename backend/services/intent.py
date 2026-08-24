"""意图识别服务：规则引擎（Agent 级）+ LLM 兜底分类

判定流程（general Agent 路由开启时，见设计文档 dev-docs/20）：
1. 规则按 priority 升序执行，命中即返回 target
2. 规则判 simple 但消息长度 > intent.simple_max_length → 不信任，升级 LLM 兜底
   （防"你好，帮我查一下报销制度"被误判 simple）
3. 无规则命中 → LLM 兜底分类（低温 JSON 输出 {"intent": ...}）
4. LLM 分类失败/超时/解析失败 → 默认 general（宁多花 token 不答错）

设计原则：general 规则可激进（误判代价 = 多花 token），simple 规则必须保守（误判代价 = 瞎编）。

注意：ChatService._is_temperature_error 在方法内延迟导入（避免循环导入，项目已有先例）。
"""
import json
import logging
import re

from backend.core.config import settings

logger = logging.getLogger(__name__)

_CLASSIFY_PROMPT_TEMPLATE = (
    "你是对话意图分类器。判断下面的用户问题是否需要调用外部能力"
    "（知识库检索、任务规划、答案反思等）。\n\n"
    "该 Agent 可用的能力：\n{tools_desc}\n\n"
    "分类规则：\n"
    "- simple：纯对话内容（问候、感谢、闲聊、基于上下文直接回答），不需要任何外部能力\n"
    "- general：需要检索知识库、制定计划、分析对比或任何工具能力\n\n"
    "只输出 JSON：{{\"intent\": \"simple\"}} 或 {{\"intent\": \"general\"}}\n"
    "不要输出解释或其他内容。\n\n"
    "用户问题：{message}"
)


class IntentService:
    """意图识别：规则引擎 + LLM 兜底分类，返回 simple 或 general"""

    @staticmethod
    async def classify(agent: object, llm_cfg: object, message: str,
                       tools_desc: str = "") -> str:
        """完整判定流程（见模块 docstring）

        参数:
            agent: general_agents ORM 对象（读 intent_routing / intent_rules）
            llm_cfg: 对话模型配置（LLM 兜底分类用）
            message: 用户当前问题
            tools_desc: 业务工具描述列表（供 LLM 判断是否需要能力）
        返回: "simple" 或 "general"
        """
        # 1. 路由开关关闭 → 纯 ReAct（不分类）
        if not getattr(agent, "intent_routing", False):
            return "general"
        # 2. 规则引擎
        try:
            intent = IntentService._match_rules(agent.intent_rules, message)
            if intent == "general":
                return "general"
            if intent == "simple":
                if len(message) <= settings.intent.simple_max_length:
                    return "simple"
                logger.info("规则判 simple 但消息过长(%d>%d)，升级 LLM 兜底",
                            len(message), settings.intent.simple_max_length)
        except Exception:
            logger.exception("意图规则引擎异常，降级 LLM 兜底")
        # 3. LLM 兜底分类
        try:
            intent = await IntentService._llm_classify(llm_cfg, message, tools_desc)
            if intent in ("simple", "general"):
                return intent
            logger.warning("LLM 分类输出非法: %r，默认 general", intent)
        except Exception:
            logger.exception("LLM 意图分类失败，默认 general")
        return "general"

    # ═══════════════════════════════════════════════
    # 规则引擎（纯函数，可独立测试）
    # ═══════════════════════════════════════════════

    @staticmethod
    def _match_rules(intent_rules, message: str) -> str | None:
        """规则引擎：priority 升序执行，命中即返回 target；无命中返回 None"""
        rules = ((intent_rules or {}).get("rules", [])
                 if isinstance(intent_rules, dict) else [])
        enabled = [r for r in rules if r.get("enabled", True)]
        enabled.sort(key=lambda r: r.get("priority", 100))
        for r in enabled:
            if IntentService._rule_hit(r, message):
                return r.get("target")
        return None

    @staticmethod
    def _rule_hit(rule: dict, message: str) -> bool:
        """单条规则命中判定：keyword 任一命中 / regex 匹配 / length 上限"""
        kind = rule.get("kind")
        if kind == "keyword":
            kws = rule.get("keywords") or []
            return any(kw and kw.lower() in message.lower() for kw in kws)
        if kind == "regex":
            try:
                return re.search(rule.get("pattern") or "", message) is not None
            except re.error:
                logger.warning("意图规则正则非法: %r", rule.get("pattern"))
                return False
        if kind == "length":
            return len(message) <= int(rule.get("max_length") or 0)
        return False

    # ═══════════════════════════════════════════════
    # LLM 兜底分类
    # ═══════════════════════════════════════════════

    @staticmethod
    async def _llm_classify(llm_cfg: object, message: str,
                            tools_desc: str) -> str | None:
        """LLM 兜底分类：低温 JSON 输出，容错解析；失败返回 None（调用方默认 general）

        推理模型（Kimi K3 / o1 等）仅支持 temperature=1：检测到温度限制错误时
        自动以 temperature=1 降级重试一次。
        """
        from backend.services.llm import LLMService

        prompt = _CLASSIFY_PROMPT_TEMPLATE.format(
            tools_desc=tools_desc or "（未声明）", message=message)
        try:
            text = await LLMService.chat(
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
                logger.warning("分类模型仅支持 temperature=1，自动用 1 重试: %s", e)
                text = await LLMService.chat(
                    provider=llm_cfg.provider,
                    model_name=llm_cfg.model_name,
                    api_key=llm_cfg.api_key,
                    base_url=llm_cfg.base_url,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=1.0,
                    top_p=0.9,
                    protocol=getattr(llm_cfg, "protocol", None),
                )
            else:
                raise
        return IntentService._parse_intent(text or "")

    @staticmethod
    def _parse_intent(text: str) -> str | None:
        """容错解析分类结果：{"intent": "simple"} / 裸 simple / 代码块包裹；失败返回 None"""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            lines = cleaned.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            cleaned = "\n".join(lines).strip()
        try:
            data = json.loads(cleaned)
            if isinstance(data, dict):
                intent = data.get("intent")
                if intent in ("simple", "general"):
                    return intent
        except Exception:
            pass
        if cleaned in ("simple", "general"):
            return cleaned
        return None
