"""Ragas 三大指标全部评估 prompt（集中一处，调优不改逻辑代码）

论文依据：Es et al., "Ragas: Automated Evaluation of Retrieval Augmented
Generation" (arXiv:2309.15217) §3。prompt 语义与论文一致，做两点工程适配：

1. 中文化：被测系统为中文问答，评审 prompt 用中文（论文原 prompt为英文）
2. JSON 化：论文用尾行 Yes/No 解析，中文长输出下结构化 JSON 解析更稳，
   指标语义（可推断=支持）不变

修改 prompt 只需改本文件；改完可用 eval_ragas.py --reuse <历史结果> 不跑 RAG 直接重评。
"""

# ── Faithfulness 忠实度 ──────────────────────────
# 论文 prompt①："Given a question and answer, create one or more statements
# from each sentence in the given answer."（陈述拆解）

FAITHFULNESS_EXTRACT_PROMPT = """给定问题和答案，将答案中的每个句子拆解为一个或多个简洁、原子化的陈述句。
要求：
- 陈述必须是可独立验证的事实断言，去掉修饰性内容；
- 只改写答案已有的信息，不得添加或推断答案之外的新内容。

问题：{question}

答案：{answer}

只输出 JSON：{{"statements": ["陈述1", "陈述2", ...]}}"""


# 论文 prompt②："Consider the given context and following statements, then
# determine whether they are supported by the information present in the
# context... (Yes/No)"（逐条验证）

FAITHFULNESS_VERIFY_PROMPT = """给定上下文和若干陈述，逐条判断每个陈述能否从上下文信息中推断得出。
要求：
- 只依据上下文本身判断，不使用任何外部知识；
- 上下文未提及、含糊或与上下文矛盾的陈述一律判 no。

上下文：
{context}

陈述列表：
{statements}

只输出 JSON：{{"verdicts": [{{"statement": "陈述原文", "verdict": "yes 或 no", "reason": "一句话依据"}}, ...]}}
verdicts 数量和顺序必须与陈述列表一一对应。"""


# ── Answer Relevance 答案相关性 ──────────────────
# 论文 prompt："Generate a question for the given answer."
# （从答案反生成问题，再算与原问题的嵌入余弦均值）

ANSWER_RELEVANCE_GEN_PROMPT = """根据以下答案生成 {num_questions} 个该答案能够直接回答的问题。
要求：
- 问题必须能由该答案直接回答，针对答案中的具体信息提问；
- 不要出现"根据材料""根据上下文"之类字样；
- 各问题从不同角度提问，不要重复。

答案：{answer}

只输出 JSON：{{"questions": ["问题1", "问题2", ...]}}"""


# ── Context Relevance 上下文相关性 ────────────────
# 论文 prompt："Please extract relevant sentences from the provided context
# that can potentially help answer the following question... you're not
# allowed to make any changes to sentences from given context."
# （原样摘录关键句，句数/总句数 = 聚焦度；论文的 "Insufficient Information"
#  在此映射为空列表，语义一致）

CONTEXT_RELEVANCE_EXTRACT_PROMPT = """请从给定上下文中原样摘录有助于回答问题的句子。
要求：
- 只能原样摘录上下文中完整出现的句子，禁止改写、概括或拼接；
- 与问题无关的句子不要摘录；
- 若上下文中没有相关句子，或认为无法从上下文回答该问题，返回空列表；
- 摘录句子按其在上下文中出现的顺序排列。

问题：{question}

上下文：
{context}

只输出 JSON：{{"sentences": ["摘录句子1", "摘录句子2", ...]}}"""
