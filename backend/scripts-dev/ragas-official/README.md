# Ragas 官方方法评估（TestsetGenerator 测试集构建 + 官方 evaluate）

按官方仓库 [vibrantlabsai/ragas](https://github.com/vibrantlabsai/ragas) 指引实现
（docs.ragas.io：*Testset Generation for RAG* + *Evaluate a simple RAG system*），
与 `../rag-eval/`（论文自实现指标）、`../bench/`（规则判定）互补。

## 与 rag-eval 的区别

| | rag-eval（自实现） | ragas-official（本目录） |
| --- | --- | --- |
| 测试集 | 手写/复用 bench 问题集（需人工标注） | **官方 TestsetGenerator 自动生成**（KnowledgeGraph + Personas + Scenarios，自带 reference 答案） |
| 指标 | 论文 §3 三指标（自实现，中文 prompt） | **官方五指标**（官方 prompt）：Faithfulness / AnswerRelevancy / ContextPrecision / ContextRecall / FactualCorrectness |
| 依赖 | 零新依赖 | `uv add --dev ragas rapidfuzz pandas nltk` |

官方独有价值：**ContextRecall/ContextPrecision/FactualCorrectness 需要 reference 答案**——
官方测试集自动生成 reference，无需人工标注；FactualCorrectness 即"答案准确率"（对 reference 的
claim 级 F1）。

## 官方三步流程

```
step1  语料(docs_dir) → TestsetGenerator → testsets/testset_<ts>.json/csv
                              （KnowledgeGraph 富化 → Personas → Scenarios → 问答对）
step2  testset.user_input → 被测 RAG([RAGEVAL] Agent) → results/rag_run_<ts>.json
                              （收集 user_input / response / retrieved_contexts）
step3  rag_run → EvaluationDataset → 官方 evaluate → results/official_eval_<ts>.json/csv
```

```bash
# 0. 依赖（已完成）：uv add --dev ragas rapidfuzz pandas nltk
# 1. 生成官方测试集（LLM 生成，一次生成反复使用；--size 默认 10）
.venv/Scripts/python backend/scripts-dev/ragas-official/step1_gen_testset.py
# 2. 被测 RAG 执行（真实调用被测 Agent）
.venv/Scripts/python backend/scripts-dev/ragas-official/step2_run_rag.py [--testset 子串] [--limit N]
# 3. 官方 evaluate（judge LLM 评审）
.venv/Scripts/python backend/scripts-dev/ragas-official/step3_evaluate.py [--run 子串] [--model kimi]
```

## 官方指标说明（[0,1] 越高越好）

| 指标 | 含义 | 依赖 |
| --- | --- | --- |
| faithfulness | 答案陈述可被 retrieved_contexts 支持的比例（幻觉反向） | LLM |
| answer_relevancy | 答案与问题的对齐度（反生成问题余弦） | LLM + Embedding |
| llm_context_precision_with_reference | 召回上下文中关键内容的精确率（排序质量） | LLM + reference |
| context_recall | reference 的要点被召回上下文覆盖的比例（检索完整性） | LLM + reference |
| factual_correctness | 答案与 reference 的 claim 级 F1（**答案准确率**） | LLM + reference |

## 文件说明

| 文件 | 说明 |
| --- | --- |
| ragas_compat.py | **兼容 shim**：ragas 0.4.3 顶层 import 已被 langchain-community 0.4.2 移除的 vertexai 模块，注入占位 stub（官方适配后可删） |
| official_config.example.yaml | 配置模板（复制为 official_config.yaml；api_key 一律从库中读取） |
| official_common.py | 公共设施：配置/模型解析/官方 wrapper 构建/被测资源准备 |
| step1/2/3 | 官方三步流程脚本 |
| tiktoken_cache/ | tiktoken 编码离线缓存（openaipublic.blob.core.windows.net 直连不稳，首次经本地代理下载；Git 忽略） |
| testsets/ results/ | 官方产物落盘（Git 忽略） |

## 已知注意事项

- ragas 生成/评审 LLM 走 OpenAI 兼容端点（`LangchainLLMWrapper(ChatOpenAI(base_url=...))`），
  glm 实测可用；AnswerRelevancy 请求 n=3 生成时 glm 只回 1 条，ragas 自动降级（仅提示）。
- 裸 `import ragas` 前必须 `ragas_compat.apply()`（三步脚本已内置）。
- 官方 evaluate 与其他 LLM 任务并行时共享厂商配额，偶发单题 judge 超时记 NaN（总分自动跳过）。
- 测试集生成受 KnowledgeGraph 覆盖影响，请求 size=10 实际产出可能为 8（官方行为）。
