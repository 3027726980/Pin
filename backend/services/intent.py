"""配置化意图识别：运行时枚举 + Pydantic 校验。

意图类别是 ``config.yaml.intent.categories`` 的启动期配置，不写死在代码中。
旧 Agent 的 ``simple/general`` 规则仍被支持：规则命中后会映射到相应类别；未命中时由
LLM 根据最近语义消息和当前问题输出 JSON，再由动态 Pydantic 枚举严格校验。
"""
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace
from typing import Any

from pydantic import create_model

from backend.core.config import settings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentPolicy:
    """一个启动期意图类别及其图编排策略。"""

    code: str
    description: str
    route: str
    use_plan: bool = False
    use_reflect: bool = False


_FALLBACK_CATEGORIES = (
    IntentPolicy("simple", "无需外部能力的直接对话", "simple"),
    IntentPolicy("general", "需要业务工具或检索的请求", "general"),
)


class IntentService:
    """为 AgentGraph 提供规则、LLM 和运行时枚举意图判定。"""

    @staticmethod
    def configured_categories() -> list[IntentPolicy]:
        """读取并校验启动期配置；历史配置缺失时保持 general 安全降级。"""
        raw_categories = getattr(getattr(settings, "intent", None), "categories", None)
        if not raw_categories:
            return list(_FALLBACK_CATEGORIES)

        categories: list[IntentPolicy] = []
        seen: set[str] = set()
        for raw in raw_categories:
            data = IntentService._to_dict(raw)
            code = str(data.get("code", "")).strip()
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", code):
                raise ValueError(f"意图类别 code 非法: {code!r}")
            if code in seen:
                raise ValueError(f"意图类别 code 重复: {code}")
            route = str(data.get("route", "general")).strip()
            if route not in {"simple", "general"}:
                raise ValueError(f"意图类别 {code} 的 route 必须是 simple 或 general")
            categories.append(IntentPolicy(
                code=code,
                description=str(data.get("description") or code),
                route=route,
                use_plan=bool(data.get("use_plan", False)),
                use_reflect=bool(data.get("use_reflect", False)),
            ))
            seen.add(code)
        return categories

    @staticmethod
    def build_decision_model(categories: list[IntentPolicy | dict] | None = None):
        """根据启动期类别构造 ``intent`` 动态枚举的 Pydantic 模型。"""
        policies = IntentService._normalize_categories(categories)
        enum_members = {policy.code.upper(): policy.code for policy in policies}
        runtime_enum = Enum("ConfiguredIntent", enum_members, type=str)
        return create_model("IntentDecision", intent=(runtime_enum, ...))

    @staticmethod
    def resolve_policy(code: str,
                       categories: list[IntentPolicy | dict] | None = None) -> IntentPolicy:
        """把经过校验的类别码映射到实际图节点策略。"""
        policies = IntentService._normalize_categories(categories)
        for policy in policies:
            if policy.code == code:
                return policy
        raise ValueError(f"未配置的意图类别: {code}")

    @staticmethod
    def default_general_policy() -> IntentPolicy:
        """分类异常时选择 general 路由，优先使用同名类别。"""
        policies = IntentService.configured_categories()
        for policy in policies:
            if policy.code == "general":
                return policy
        return next((policy for policy in policies if policy.route == "general"), policies[0])

    @staticmethod
    def classify_by_rules(agent: object, message: str) -> str | None:
        """执行旧版 Agent 二元规则，并映射成配置化类别码。"""
        target = IntentService._match_rules(getattr(agent, "intent_rules", None), message)
        if not target:
            return None
        policies = IntentService.configured_categories()
        # 前端旧规则 target 固定 simple/general；允许未来直接写新类别 code。
        exact = next((policy for policy in policies if policy.code == target), None)
        if exact:
            return exact.code
        by_route = next((policy for policy in policies if policy.route == target), None)
        return by_route.code if by_route else None

    @staticmethod
    async def classify(agent: object, llm_cfg: object, message: str,
                       tools_desc: str = "", history: list[dict[str, str]] | None = None) -> str:
        """返回已配置的意图类别码；任何异常都安全降级至 general 路由。"""
        fallback = IntentService.default_general_policy().code
        if not getattr(agent, "intent_routing", False):
            return fallback

        try:
            intent = IntentService.classify_by_rules(agent, message)
            if intent:
                policy = IntentService.resolve_policy(intent)
                max_len = getattr(settings.intent, "simple_max_length", 30)
                if policy.route != "simple" or len(message) <= max_len:
                    return intent
                logger.info("规则判定为 simple 路由但问题过长，转 LLM 分类")
        except Exception:
            logger.exception("意图规则引擎异常，降级 LLM 分类")

        try:
            intent = await IntentService._llm_classify(
                llm_cfg, message, tools_desc, history or [])
            if intent:
                return intent
        except Exception:
            logger.exception("LLM 意图分类失败，默认 general")
        return fallback

    @staticmethod
    def _match_rules(intent_rules: Any, message: str) -> str | None:
        """规则按 priority 升序命中，兼容 JSONB 字典。"""
        rules = ((intent_rules or {}).get("rules", [])
                 if isinstance(intent_rules, dict) else [])
        enabled = [rule for rule in rules if rule.get("enabled", True)]
        enabled.sort(key=lambda rule: rule.get("priority", 100))
        for rule in enabled:
            if IntentService._rule_hit(rule, message):
                target = rule.get("target")
                return str(target) if target else None
        return None

    @staticmethod
    def _rule_hit(rule: dict, message: str) -> bool:
        """单条 keyword / regex / length 规则判定。"""
        kind = rule.get("kind")
        if kind == "keyword":
            return any(word and word.lower() in message.lower()
                       for word in (rule.get("keywords") or []))
        if kind == "regex":
            try:
                return re.search(rule.get("pattern") or "", message) is not None
            except re.error:
                logger.warning("意图规则正则非法: %r", rule.get("pattern"))
                return False
        if kind == "length":
            return len(message) <= int(rule.get("max_length") or 0)
        return False

    @staticmethod
    async def _llm_classify(llm_cfg: object, message: str, tools_desc: str,
                            history: list[dict[str, str]]) -> str | None:
        """让 LLM 按动态 JSON Schema 输出，再由 Pydantic 校验。"""
        from backend.services.llm import LLMService

        categories = IntentService.configured_categories()
        decision_model = IntentService.build_decision_model(categories)
        category_text = "\n".join(
            f"- {policy.code}: {policy.description}（route={policy.route}，"
            f"plan={policy.use_plan}，reflect={policy.use_reflect}）"
            for policy in categories
        )
        history_text = "\n".join(
            f"{item.get('role', 'user')}：{str(item.get('content', ''))[:500]}"
            for item in history[-5:]
        ) or "（无历史消息）"
        prompt = (
            "你是对话意图分类器。根据最近对话和当前问题选择一个已配置类别。\n\n"
            f"可用类别：\n{category_text}\n\n"
            f"业务工具：\n{tools_desc or '（无业务工具）'}\n\n"
            f"最近对话（最多 5 条）：\n{history_text}\n\n"
            f"当前问题：{message}\n\n"
            "只输出符合以下 JSON Schema 的 JSON，不输出解释：\n"
            f"{json.dumps(decision_model.model_json_schema(), ensure_ascii=False)}"
        )

        async def call(temperature: float) -> str:
            return await LLMService.chat(
                provider=llm_cfg.provider,
                model_name=llm_cfg.model_name,
                api_key=llm_cfg.api_key,
                base_url=llm_cfg.base_url,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                top_p=0.9,
                protocol=getattr(llm_cfg, "protocol", None),
            )

        temperature = getattr(settings.intent, "classify_temperature", 0.2)
        try:
            text = await call(temperature)
        except Exception as exc:
            from backend.services.chat import ChatService

            if not ChatService._is_temperature_error(exc):
                raise
            logger.warning("分类模型仅支持 temperature=1，自动重试")
            text = await call(1.0)
        return IntentService._parse_intent(text or "", categories)

    @staticmethod
    def _parse_intent(text: str,
                      categories: list[IntentPolicy | dict] | None = None) -> str | None:
        """解析 JSON 并通过动态 Pydantic 枚举校验；拒绝裸文本和未配置值。"""
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
            decision = IntentService.build_decision_model(categories).model_validate(data)
            return decision.intent.value
        except Exception:
            return None

    @staticmethod
    def _normalize_categories(categories: list[IntentPolicy | dict] | None) -> list[IntentPolicy]:
        """把显式测试配置或全局配置统一成已校验策略对象。"""
        if categories is None:
            return IntentService.configured_categories()
        normalized: list[IntentPolicy] = []
        for item in categories:
            if isinstance(item, IntentPolicy):
                normalized.append(item)
                continue
            data = IntentService._to_dict(item)
            normalized.append(IntentPolicy(
                code=str(data["code"]),
                description=str(data.get("description") or data["code"]),
                route=str(data.get("route", "general")),
                use_plan=bool(data.get("use_plan", False)),
                use_reflect=bool(data.get("use_reflect", False)),
            ))
        if not normalized:
            raise ValueError("至少需要一个意图类别")
        return normalized

    @staticmethod
    def _to_dict(value: Any) -> dict:
        """兼容 config 的 SimpleNamespace 和普通字典。"""
        if isinstance(value, dict):
            return value
        if isinstance(value, SimpleNamespace):
            return vars(value)
        raise ValueError("意图类别配置必须是对象")
