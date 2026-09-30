"""统一模型调用参数、厂商能力与单 Turn 预算。"""

import time
from contextlib import asynccontextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass, field


def normalize_sampling_params(
    provider: str,
    model_name: str,
    temperature: float,
    top_p: float,
) -> tuple[float, float]:
    """按已知模型能力在请求发出前归一化采样参数。"""
    normalized_model = model_name.strip().lower()
    normalized_provider = provider.strip().lower()
    if normalized_model.startswith("kimi-k2.6") or (
        normalized_provider in {"moonshot", "kimi"}
        and normalized_model.startswith("kimi-k2")
    ):
        return 1.0, 0.95
    return temperature, top_p


def model_requests_per_minute(provider: str, model_name: str) -> int | None:
    """返回已知低配额模型的请求上限，未知模型不主动限流。"""
    model = model_name.strip().lower()
    vendor = provider.strip().lower()
    if model.startswith("kimi-k2.6") or (
        vendor in {"moonshot", "kimi"} and model.startswith("kimi-k2")
    ):
        return 3
    return None


@dataclass(frozen=True, slots=True)
class ModelInvocationConfig:
    """所有直接调用和 LangChain 模型构造共用的最终参数。"""

    provider: str
    model_name: str
    api_key: str = field(repr=False)
    base_url: str | None
    protocol: str | None
    temperature: float
    top_p: float
    max_tokens: int | None
    timeout: float
    max_retries: int


class BudgetExceeded(RuntimeError):
    """单 Turn 调用次数或截止时间耗尽。"""


@dataclass(slots=True)
class TurnBudget:
    """所有节点共享的调用与墙钟预算。"""

    max_llm_calls: int
    max_tool_calls: int
    deadline_ms: int
    llm_calls_used: int = 0
    tool_calls_used: int = 0
    started_at: float = field(default_factory=time.perf_counter)

    @property
    def remaining_ms(self) -> int:
        """返回截止时间前剩余毫秒。"""
        elapsed = int((time.perf_counter() - self.started_at) * 1000)
        return max(0, self.deadline_ms - elapsed)

    def acquire_llm(self) -> None:
        """占用一次模型调用资格。"""
        self._check_deadline()
        if self.llm_calls_used >= self.max_llm_calls:
            raise BudgetExceeded("max_llm_calls exceeded")
        self.llm_calls_used += 1

    def acquire_tool(self) -> None:
        """占用一次工具调用资格。"""
        self._check_deadline()
        if self.tool_calls_used >= self.max_tool_calls:
            raise BudgetExceeded("max_tool_calls exceeded")
        self.tool_calls_used += 1

    def _check_deadline(self) -> None:
        if self.remaining_ms <= 0:
            raise BudgetExceeded("turn deadline exceeded")


_TURN_BUDGET: ContextVar[TurnBudget | None] = ContextVar("turn_budget", default=None)


def current_turn_budget() -> TurnBudget | None:
    """获取当前异步上下文的 Turn 预算。"""
    return _TURN_BUDGET.get()


@asynccontextmanager
async def bind_turn_budget(budget: TurnBudget):
    """在当前异步执行链绑定统一预算。"""
    token: Token = _TURN_BUDGET.set(budget)
    try:
        yield budget
    finally:
        _TURN_BUDGET.reset(token)


def _first_not_none(*values: object) -> object | None:
    """返回第一个不为 None 的值。"""
    return next((value for value in values if value is not None), None)


def build_model_invocation_config(
    model_config: object,
    *,
    agent: object | None = None,
    temperature: float | None = None,
    top_p: float | None = None,
    max_tokens: int | None = None,
    timeout: float = 60.0,
) -> ModelInvocationConfig:
    """按显式值、Agent、模型配置和系统默认值解析最终调用参数。"""
    resolved_temperature = float(
        _first_not_none(
            temperature,
            getattr(agent, "temperature", None) if agent is not None else None,
            getattr(model_config, "temperature", None),
            0.7,
        )
    )
    resolved_top_p = float(
        _first_not_none(
            top_p,
            getattr(agent, "top_p", None) if agent is not None else None,
            getattr(model_config, "top_p", None),
            0.9,
        )
    )
    resolved_max_tokens = _first_not_none(
        max_tokens,
        getattr(agent, "max_tokens", None) if agent is not None else None,
        getattr(model_config, "max_tokens", None),
    )
    provider = str(getattr(model_config, "provider", ""))
    model_name = str(getattr(model_config, "model_name"))
    resolved_temperature, resolved_top_p = normalize_sampling_params(
        provider, model_name, resolved_temperature, resolved_top_p
    )
    return ModelInvocationConfig(
        provider=provider,
        model_name=model_name,
        api_key=str(getattr(model_config, "api_key", "") or ""),
        base_url=getattr(model_config, "base_url", None),
        protocol=getattr(model_config, "protocol", None),
        temperature=resolved_temperature,
        top_p=resolved_top_p,
        max_tokens=(
            int(resolved_max_tokens) if resolved_max_tokens is not None else None
        ),
        timeout=float(timeout),
        max_retries=0,
    )


__all__ = [
    "BudgetExceeded",
    "ModelInvocationConfig",
    "TurnBudget",
    "bind_turn_budget",
    "build_model_invocation_config",
    "model_requests_per_minute",
    "current_turn_budget",
    "normalize_sampling_params",
]
