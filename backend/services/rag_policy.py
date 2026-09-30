"""无需 LLM 的自适应 RAG 决策器。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

RagMode = Literal["off", "auto", "always"]
RagStrategy = Literal["base", "mqe", "hyde", "hybrid"]


def resolve_rag_mode(
    mode: str | None,
    legacy_enabled: bool | None,
    *,
    default: RagMode = "auto",
) -> RagMode:
    """新 mode 优先；旧布尔显式值映射为 always/off；新建默认 auto。"""
    if mode in {"off", "auto", "always"}:
        return mode  # type: ignore[return-value]
    if legacy_enabled is not None:
        return "always" if legacy_enabled else "off"
    return default


@dataclass(frozen=True, slots=True)
class RetrievalSignals:
    """原始 query 召回和问题特征。"""

    query_length: int
    is_follow_up: bool
    is_multi_part: bool
    is_conceptual: bool
    top1_score: float | None
    top3_avg: float | None
    above_threshold_count: int
    document_diversity: int
    threshold: float


@dataclass(frozen=True, slots=True)
class RagDecision:
    """增强策略、Rerank 决策及可审计原因。"""

    strategy: RagStrategy
    rerank: bool
    reason_codes: tuple[str, ...]


class RagPolicy:
    """根据原始召回质量与显式模式做确定性选择，不新增模型调用。"""

    @staticmethod
    def decide(
        signals: RetrievalSignals,
        *,
        mqe_mode: RagMode,
        hyde_mode: RagMode,
        rerank_mode: RagMode,
        auto_budget_available: bool = True,
    ) -> RagDecision:
        """选择 base/mqe/hyde/hybrid，并分别控制 Rerank。"""
        reasons: list[str] = []
        top1 = signals.top1_score
        high = (
            top1 is not None
            and top1 >= signals.threshold + 0.15
            and signals.above_threshold_count >= 2
            and (signals.top3_avg or 0) >= signals.threshold + 0.08
        )
        low = (
            top1 is None
            or signals.above_threshold_count == 0
            or top1 < signals.threshold + 0.05
        )
        reasons.append("confidence_high" if high else "confidence_low" if low else "confidence_medium")

        forced_mqe = mqe_mode == "always"
        forced_hyde = hyde_mode == "always"
        want_mqe = forced_mqe
        want_hyde = forced_hyde

        if auto_budget_available and not high:
            if mqe_mode == "auto" and (signals.is_multi_part or signals.is_follow_up):
                want_mqe = True
                reasons.append("query_multi_or_follow_up")
            if hyde_mode == "auto" and (signals.is_conceptual or signals.query_length <= 16):
                want_hyde = True
                reasons.append("query_conceptual_or_short")
            if low and not (want_mqe or want_hyde):
                if mqe_mode == "auto":
                    want_mqe = True
                    reasons.append("low_recall_expand")
                elif hyde_mode == "auto":
                    want_hyde = True
                    reasons.append("low_recall_hypothesis")
        elif not auto_budget_available and (mqe_mode == "auto" or hyde_mode == "auto"):
            reasons.append("auto_budget_exhausted")

        strategy: RagStrategy = (
            "hybrid" if want_mqe and want_hyde
            else "mqe" if want_mqe
            else "hyde" if want_hyde
            else "base"
        )
        rerank = rerank_mode == "always" or (
            rerank_mode == "auto"
            and auto_budget_available
            and signals.above_threshold_count >= 2
            and (not high or signals.document_diversity > 1)
        )
        if rerank:
            reasons.append("rerank_for_competing_candidates")
        return RagDecision(strategy=strategy, rerank=rerank, reason_codes=tuple(reasons))


__all__ = [
    "RagDecision", "RagMode", "RagPolicy", "RetrievalSignals", "resolve_rag_mode",
]
