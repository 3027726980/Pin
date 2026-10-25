"""作者：LHF；时间：2026-10-25；作用：意图类别只决定规划和核验，所有请求进入统一主 Agent。"""
import json
import logging
import re
from dataclasses import dataclass
from enum import Enum
from types import SimpleNamespace

from pydantic import create_model
from backend.core.config import settings
from backend.core.observability.operations import Operation

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IntentPolicy:
    """可配置类别及可选规划、核验策略。"""

    code: str
    description: str
    use_plan: bool = False
    use_reflect: bool = False


class IntentService:
    """规则和模型共享类别校验，不裁减主 Agent 能力。"""

    @staticmethod
    def configured_categories():
        """读取配置类别，忽略已移除的轻量类别。"""
        raw = getattr(getattr(settings, "intent", None), "categories", None) or []
        values = [IntentService._to_dict(item) for item in raw]
        values = [item for item in values if item.get("code") != "simple"]
        return IntentService._normalize_categories(values or [
            {"code": "general", "description": "常规请求"},
            {"code": "complex", "description": "多步骤分析或高准确度任务", "use_plan": True, "use_reflect": True},
        ])

    @staticmethod
    def _normalize_categories(categories):
        """校验类别名称、重复项和执行策略。"""
        if categories is None:
            return IntentService.configured_categories()
        result, seen = [], set()
        for value in categories:
            item = value if isinstance(value, IntentPolicy) else IntentPolicy(
                code=str(value["code"]), description=str(value.get("description") or value["code"]),
                use_plan=bool(value.get("use_plan", False)), use_reflect=bool(value.get("use_reflect", False)))
            if not re.fullmatch(r"[a-z][a-z0-9_]{0,31}", item.code) or item.code in seen:
                raise ValueError(f"意图类别非法或重复：{item.code}")
            seen.add(item.code)
            result.append(item)
        if not result:
            raise ValueError("至少需要一个意图类别")
        return result

    @staticmethod
    def build_decision_model(categories=None):
        """按当前类别生成结构化输出枚举。"""
        policies = IntentService._normalize_categories(categories)
        enum_type = Enum("ConfiguredIntent", {item.code.upper(): item.code for item in policies}, type=str)
        return create_model("IntentDecision", intent=(enum_type, ...))

    @staticmethod
    def resolve_policy(code, categories=None):
        """读取已验证类别的执行策略。"""
        for item in IntentService._normalize_categories(categories):
            if item.code == code:
                return item
        raise ValueError(f"未配置的意图类别：{code}")

    @staticmethod
    def default_general_policy():
        """关闭或失败时选择常规策略。"""
        policies = IntentService.configured_categories()
        return next((item for item in policies if item.code == "general"), policies[0])

    @staticmethod
    def classify_by_rules(agent, message, *, diagnostics=None):
        """规则直接映射到配置类别码，忽略失效目标。"""
        target = IntentService._match_rules(getattr(agent, "intent_rules", None), message, diagnostics=diagnostics)
        return target if target in {item.code for item in IntentService.configured_categories()} else None

    @staticmethod
    async def classify(agent, llm_cfg, message, tools_desc="", history=None):
        """保留完整判定依据，类别仅决定规划及核验。"""
        with Operation("intent", "意图识别", input={"message": message, "history": history or [],
                       "tools_description": tools_desc}, metadata={}) as operation:
            result = await IntentService._classify(agent, llm_cfg, message, tools_desc, history or [], operation)
            policy = IntentService.resolve_policy(result)
            operation.output = {"intent_code": policy.code,
                                "use_plan": policy.use_plan and bool(getattr(agent, "plan_enabled", True)),
                                "use_reflect": policy.use_reflect and bool(getattr(agent, "reflect_enabled", True))}
            return result

    @staticmethod
    async def _classify(agent, llm_cfg, message, tools_desc, history, operation):
        """优先规则，未命中调用模型；异常保留诊断并降级。"""
        fallback = IntentService.default_general_policy().code
        if not getattr(agent, "intent_routing", False):
            operation.metadata["source"] = "routing_disabled"
            return fallback
        result = IntentService.classify_by_rules(agent, message, diagnostics=operation.metadata)
        if result:
            operation.metadata["source"] = "rule"
            return result
        try:
            operation.metadata.update(source="model", model=getattr(llm_cfg, "model_name", None),
                                      provider=getattr(llm_cfg, "provider", None))
            result = await IntentService._llm_classify(llm_cfg, message, tools_desc, history)
            if result:
                return result
        except Exception as error:
            operation.metadata["fallback_reason"] = {"type": type(error).__name__, "message": str(error)}
            logger.exception("意图分类失败，保留常规主 Agent")
        operation.status = "degraded"
        operation.metadata["source"] = "fallback"
        operation.metadata.setdefault("fallback_reason", "invalid_classification_result")
        return fallback

    @staticmethod
    def _match_rules(intent_rules, message, *, diagnostics=None):
        """按优先级运行规则，记录实际评估条件。"""
        rules = intent_rules.get("rules", []) if isinstance(intent_rules, dict) else []
        categories = {item.code for item in IntentService.configured_categories()}
        for rule in sorted((item for item in rules if item.get("enabled", True)), key=lambda item: item.get("priority", 100)):
            if rule.get("target") not in categories:
                continue
            hit = IntentService._rule_hit(rule, message)
            if diagnostics is not None:
                diagnostics.setdefault("evaluated_rules", []).append({"rule": dict(rule), "matched": hit})
                if hit:
                    diagnostics["matched_rule"] = dict(rule)
            if hit:
                return rule["target"]
        return None

    @staticmethod
    def _rule_hit(rule, message):
        """支持关键词、正则及长度条件。"""
        if rule.get("kind") == "keyword":
            return any(word and word.casefold() in message.casefold() for word in rule.get("keywords") or [])
        if rule.get("kind") == "regex":
            try:
                return bool(rule.get("pattern")) and re.search(rule["pattern"], message) is not None
            except re.error:
                return False
        if rule.get("kind") == "length":
            return len(message) <= int(rule.get("max_length") or 0)
        return False

    @staticmethod
    async def _llm_classify(llm_cfg, message, tools_desc, history):
        """按配置 Schema 分类，所有类别均使用同一主 Agent。"""
        from backend.services.llm import LLMService
        from backend.services.model_policy import build_model_invocation_config

        model = IntentService.build_decision_model()
        policies = IntentService.configured_categories()
        prompt = ("根据完整任务选择意图类别。分类只决定规划和核验，不决定工具或技能调用。\n"
                  + "\n".join(f"{item.code}: {item.description}" for item in policies)
                  + f"\n可用能力：{tools_desc}\n历史：{json.dumps(history[-5:], ensure_ascii=False)}"
                    f"\n当前任务：{message}\n只输出此 Schema 的 JSON：{json.dumps(model.model_json_schema(), ensure_ascii=False)}")
        config = build_model_invocation_config(llm_cfg, temperature=getattr(settings.intent, "classify_temperature", 0.2))
        raw = await LLMService.chat(provider=config.provider, model_name=config.model_name, api_key=config.api_key,
                                    base_url=config.base_url, protocol=config.protocol,
                                    messages=[{"role": "user", "content": prompt}], temperature=config.temperature,
                                    top_p=config.top_p, max_tokens=config.max_tokens, timeout=config.timeout, purpose="intent")
        return IntentService._parse_intent(raw, policies)

    @staticmethod
    def _parse_intent(text, categories=None):
        """兼容 JSON 围栏，严格按类别枚举校验。"""
        try:
            cleaned = re.sub(r"^\x60\x60\x60(?:json)?\s*|\s*\x60\x60\x60$", "", str(text).strip())
            decision = IntentService.build_decision_model(categories).model_validate_json(cleaned)
            return decision.intent.value
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _to_dict(value):
        """兼容 YAML 配置对象。"""
        if isinstance(value, dict):
            return value
        if isinstance(value, SimpleNamespace):
            return vars(value)
        raise ValueError("类别配置必须是对象")
