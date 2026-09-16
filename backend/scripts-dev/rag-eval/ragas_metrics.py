"""Ragas 论文三大指标实现（reference-free，纯函数式，可独立复用）

论文依据：Es et al., "Ragas: Automated Evaluation of Retrieval Augmented
Generation" (arXiv:2309.15217) §3。与论文的对应关系：

- faithfulness      §3 Faithfulness        F = |V| / |S|
- answer_relevance  §3 Answer relevance    AR = (1/n) · Σ cos(q, q_i)
- context_relevance §3 Context relevance   CR = |Sext| / |S(c)|

与论文实现的三点工程适配（不改变指标语义，见 prompts.py 说明）：
1. LLM 输出用结构化 JSON（论文用 Yes/No 尾行解析）
2. 句子切分按中文标点（。！？；等）
3. 上下文超长截断（max_context_chars），统计分母与判定输入同源

约定：所有指标返回 {"score": float | None, "details": {...}}；
score=None 表示该样本该指标无意义或评估调用失败（降级不阻断，与项目
RAG 增强 MQE/HyDE/Rerank 的降级理念一致）。detail 保留中间产物便于调 prompt。
"""
import json
import math
import re

from prompts import (
    ANSWER_RELEVANCE_GEN_PROMPT,
    CONTEXT_RELEVANCE_EXTRACT_PROMPT,
    FAITHFULNESS_EXTRACT_PROMPT,
    FAITHFULNESS_VERIFY_PROMPT,
)

# 三大指标名（eval_ragas.py --metrics 参数的合法值与默认全集）
METRIC_NAMES = ("faithfulness", "answer_relevance", "context_relevance")

# 上下文拼接的分段标号格式
_CTX_SEP = "\n\n"


# ── 通用工具 ──────────────────────────────

_SENTENCE_RE = re.compile(r"[^。！？!?；;\n]+[。！？!?；;]?")


def split_sentences(text: str) -> list[str]:
    """按中文标点/换行切句（CR 指标分母与关键句校验共用）

    参数:
        text: 待切分文本（多个召回片段已拼接）

    返回:
        list[str]: 非空句子列表（保留句末标点）
    """
    return [s.strip() for s in _SENTENCE_RE.findall(text or "") if s.strip()]


def _norm(s: str) -> str:
    """归一化文本用于子串匹配：去全部空白（LLM 摘录常在标点后带空格）"""
    return re.sub(r"\s+", "", s)


def cosine(a: list[float], b: list[float]) -> float:
    """余弦相似度（纯 Python，避免为评估脚本引入 numpy 依赖）"""
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def _parse_json(text: str) -> dict:
    """解析 LLM 输出 JSON：兼容 ```json 代码块包围与前后杂文本"""
    cleaned = (text or "").strip()
    if cleaned.startswith("```"):
        cleaned = "\n".join(cleaned.splitlines()[1:-1])
    cleaned = cleaned.strip().removeprefix("json").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        # 兜底：截取首个 { 到最后一个 } 再试一次
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start >= 0 and end > start:
            return json.loads(cleaned[start:end + 1])
        raise


async def _call_judge_json(llm_cfg, prompt: str, temperature: float = 0.0) -> dict:
    """用评审模型执行一次 prompt 调用并解析 JSON 输出

    参数:
        llm_cfg: UserModelConfig ORM（provider/model_name/api_key/base_url）
        prompt: 完整 prompt 文本
        temperature: 采样温度（判定类 0，生成类可调高）

    返回:
        dict: LLM 输出的 JSON 对象
    """
    from backend.services.llm import LLMService

    text = await LLMService.chat(
        provider=llm_cfg.provider, model_name=llm_cfg.model_name,
        api_key=llm_cfg.api_key, base_url=llm_cfg.base_url,
        messages=[{"role": "user", "content": prompt}],
        temperature=temperature, top_p=0.9)
    return _parse_json(text)


def _join_contexts(contexts: list[str], max_chars: int) -> str:
    """召回片段拼接为带编号分段的上下文文本，超长截断

    截断发生在拼接后：分句统计与 LLM 判定看到的是同一段文本（分母同源）。
    """
    joined = _CTX_SEP.join(
        f"[片段{i}] {c}" for i, c in enumerate(contexts, 1))
    return joined[:max_chars]


# ── 指标一：Faithfulness 忠实度（F = |V| / |S|） ──

async def faithfulness(question: str, answer: str, contexts: list[str],
                       llm_cfg, max_context_chars: int = 4000) -> dict:
    """忠实度：答案拆成陈述后，可从召回上下文推断的比例（衡量幻觉）

    参数:
        question: 原始问题
        answer: 被测系统生成的答案
        contexts: 召回切片原文列表（citations 的 content）
        llm_cfg: 评审 LLM 配置
        max_context_chars: 参与验证的上下文最大字符数

    返回:
        dict: {"score": F | None, "details": {statements, verdicts, note?}}
    """
    context = _join_contexts(contexts, max_context_chars)
    if not context.strip():
        return {"score": 0.0, "details": {"note": "无召回上下文，答案不可证实"}}

    try:
        extracted = await _call_judge_json(
            llm_cfg, FAITHFULNESS_EXTRACT_PROMPT.format(
                question=question, answer=answer))
        statements = [str(s).strip() for s in (extracted.get("statements") or [])
                      if str(s).strip()]
        if not statements:
            return {"score": None,
                    "details": {"note": "答案未拆解出可验证陈述（如拒答/空答）",
                                "statements": []}}

        numbered = "\n".join(f"{i}. {s}" for i, s in enumerate(statements, 1))
        verified = await _call_judge_json(
            llm_cfg, FAITHFULNESS_VERIFY_PROMPT.format(
                context=context, statements=numbered))
        verdicts = verified.get("verdicts") or []
        yes = sum(1 for v in verdicts
                  if str((v or {}).get("verdict", "")).strip().lower() == "yes")
        # 分母固定为论文的 |S|（陈述总数）；verdicts 缺项按 no 计（保守）
        score = yes / len(statements)
        details = {"statements": statements, "verdicts": verdicts}
        if len(verdicts) != len(statements):
            details["note"] = (f"verdicts 数({len(verdicts)})与陈述数"
                               f"({len(statements)})不一致，缺项按 no 计")
        return {"score": score, "details": details}
    except Exception as e:  # 降级不阻断
        return {"score": None, "details": {"note": f"评估调用失败: {e}"[:200]}}


# ── 指标二：Answer Relevance（AR = mean cos(q, q_i)） ──

async def answer_relevance(question: str, answer: str, llm_cfg, embed_cfg,
                           num_questions: int = 3,
                           temperature: float = 0.7) -> dict:
    """答案相关性：从答案反生成 n 个问题，与原问题的嵌入余弦均值

    参数:
        question: 原始问题
        answer: 被测系统生成的答案
        llm_cfg: 评审 LLM 配置（负责反生成问题）
        embed_cfg: Embedding 模型配置（UserModelConfig，model_type=1）
        num_questions: 反生成问题数 n（论文未固定，ragas 库惯用 3）
        temperature: 反生成问题温度（多样性）

    返回:
        dict: {"score": AR | None, "details": {generated_questions, sims, note?}}
    """
    if not (answer or "").strip():
        return {"score": None, "details": {"note": "答案为空，无法反生成问题"}}
    try:
        from backend.services.embedding import EmbeddingService

        generated = await _call_judge_json(
            llm_cfg, ANSWER_RELEVANCE_GEN_PROMPT.format(
                num_questions=num_questions, answer=answer),
            temperature=temperature)
        questions = [str(q).strip() for q in (generated.get("questions") or [])
                     if str(q).strip()][:num_questions]
        if not questions:
            return {"score": None, "details": {"note": "反生成问题为空"}}

        vectors = EmbeddingService.embed(
            provider=embed_cfg.provider, model_name=embed_cfg.model_name,
            api_key=embed_cfg.api_key, base_url=embed_cfg.base_url,
            texts=[question] + questions)
        q_vec = vectors[0]
        sims = [cosine(q_vec, vectors[i]) for i in range(1, len(vectors))]
        return {"score": sum(sims) / len(sims),
                "details": {"generated_questions": questions, "sims": sims}}
    except Exception as e:  # 降级不阻断
        return {"score": None, "details": {"note": f"评估调用失败: {e}"[:200]}}


# ── 指标三：Context Relevance（CR = |Sext| / |S(c)|） ──

async def context_relevance(question: str, contexts: list[str], llm_cfg,
                            max_context_chars: int = 4000) -> dict:
    """上下文相关性：召回上下文中关键句占比（越低说明冗余越多）

    参数:
        question: 原始问题
        contexts: 召回切片原文列表
        llm_cfg: 评审 LLM 配置
        max_context_chars: 参与评估的上下文最大字符数

    返回:
        dict: {"score": CR | None,
               "details": {total_sentences, matched, unmatched, extracted_raw, note?}}
    """
    context = _join_contexts(contexts, max_context_chars)
    if not context.strip():
        return {"score": None, "details": {"note": "无召回上下文，指标无意义"}}
    try:
        total = len(split_sentences(context))
        if total == 0:
            return {"score": None, "details": {"note": "上下文无可切分句子"}}

        extracted = await _call_judge_json(
            llm_cfg, CONTEXT_RELEVANCE_EXTRACT_PROMPT.format(
                question=question, context=context))
        raw = [str(s).strip() for s in (extracted.get("sentences") or [])
               if str(s).strip()]

        # 原样性校验：LLM 返回句必须（去空白后）是上下文的子串，防改写/编造
        norm_ctx = _norm(context)
        matched, unmatched = [], []
        for s in raw:
            (matched if _norm(s) in norm_ctx else unmatched).append(s)
        return {"score": len(matched) / total,
                "details": {"total_sentences": total, "matched": matched,
                            "unmatched": unmatched, "extracted_raw": raw}}
    except Exception as e:  # 降级不阻断
        return {"score": None, "details": {"note": f"评估调用失败: {e}"[:200]}}


# ── 汇总入口 ──────────────────────────────

async def evaluate_sample(question: str, answer: str, contexts: list[str],
                          judge_llm_cfg, embed_cfg, metrics_cfg: dict,
                          metrics: list[str] | None = None) -> dict:
    """对单个样本执行选定指标集合

    参数:
        question / answer / contexts: 被测样本三元数据（contexts 为召回切片原文）
        judge_llm_cfg: 评审 LLM 配置
        embed_cfg: Embedding 模型配置（answer_relevance 用）
        metrics_cfg: eval_config.yaml 的 metrics 节点（各指标参数）
        metrics: 要执行的指标名列表，None = 全部（METRIC_NAMES）

    返回:
        dict: {指标名: {"score": ..., "details": ...}}（未选指标不出现）
    """
    selected = metrics or list(METRIC_NAMES)
    out: dict = {}
    if "faithfulness" in selected:
        out["faithfulness"] = await faithfulness(
            question, answer, contexts, judge_llm_cfg,
            max_context_chars=metrics_cfg.get("faithfulness", {})
            .get("max_context_chars", 4000))
    if "answer_relevance" in selected:
        ar_cfg = metrics_cfg.get("answer_relevance", {})
        out["answer_relevance"] = await answer_relevance(
            question, answer, judge_llm_cfg, embed_cfg,
            num_questions=int(ar_cfg.get("num_questions", 3)),
            temperature=float(ar_cfg.get("temperature", 0.7)))
    if "context_relevance" in selected:
        out["context_relevance"] = await context_relevance(
            question, contexts, judge_llm_cfg,
            max_context_chars=metrics_cfg.get("context_relevance", {})
            .get("max_context_chars", 4000))
    return out
