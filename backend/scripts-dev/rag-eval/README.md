# RAG 质量评估脚本使用手册（Ragas 论文指标）

依据论文：Es et al., *Ragas: Automated Evaluation of Retrieval Augmented Generation*
（arXiv:2309.15217），实现其 §3 的 **三大 reference-free 指标**，自动评估项目
simple_rag Agent 的端到端 RAG 质量。设计文档：`dev-docs/29-rag-eval-ragas-metrics-design.md`。

与 `../bench/`（关键词命中/MRR 等规则判定）互补：bench 看"检索找没找到"，
本评估看"检索上下文质量 + 生成忠实度"的端到端效果。两者代码互不依赖。

## 指标说明（论文 §3，均为 [0,1] 越高越好）

| 指标 | 论文公式 | 含义 | 需要的调用 |
| --- | --- | --- | --- |
| faithfulness 忠实度 | F = \|V\| / \|S\| | 答案拆成陈述 S，能从召回上下文推断的 V；低=幻觉 | 每题 2 次 LLM |
| answer_relevance 答案相关性 | AR = (1/n)·Σcos(q, qᵢ) | 从答案反生成 n 个问题，与原问题嵌入余弦均值；低=答非所问/冗余 | 每题 1 次 LLM + 1 次 embedding |
| context_relevance 上下文相关性 | CR = \|Sext\| / \|S(c)\| | 召回上下文中关键句占比；低=检索冗余（top_k 过大信号） | 每题 1 次 LLM |

三项指标均为 reference-free：**不需要标准答案**，问题集只需提供 question。
全部分数失败降级为 `-`（None）不阻断整体评估。

## 文件说明

| 文件/目录 | 说明 |
| --- | --- |
| eval_config.yaml | 评估配置（含 api_key，Git 忽略；从 example 复制） |
| eval_config.example.yaml | 配置模板（脱敏入库） |
| prompts.py | 三大指标全部评估 prompt（集中一处，调优不改逻辑代码） |
| ragas_metrics.py | 论文三大指标纯函数实现（可独立复用/单测） |
| eval_common.py | 公共设施：环境/模型配置/token 捕获/KB/Agent/落盘（含自检入口） |
| eval_ragas.py | 主脚本：准备资源 → 逐题 RAG → 逐题评分 → 汇总 |
| questions/*.json | 问题集（Git 忽略；可直接用 --questions 引用 bench 的问题集） |
| results/*.json | 结果落盘（Git 忽略） |

## 问题集格式（创建测试用例）

放 `questions/` 下，每套一个 JSON（**兼容 bench 问题集格式，可直接引用**）：

```json
{
  "name": "我的问题集",
  "description": "说明",
  "questions": [
    {
      "text": "公司上班时间是几点到几点？",
      "expect_doc": "考勤",
      "keyword_groups": [["9:00"], ["18:00"]],
      "reference_answer": "9:00-18:00（可选，仅存档供人工对照，不参与评分）"
    }
  ]
}
```

- **text 必需**；其余字段可选，原样保留在结果 detail 中供人工对照
- ragas 指标是 reference-free 的：`expect_doc` / `keyword_groups` / `reference_answer`
  不参与评分（想测检索命中率请用 bench）
- 新建测试用例 = 新增一个 JSON 文件，`--questions <文件名子串>` 指定

## 0. 前置条件

- PostgreSQL（pin_dev 库）运行中
- admin 名下已配置：LLM（model_type=2，必需）、Embedding（=1，可缺省用本地 bge）
- 无需启动后端/前端（脚本直调服务层），无需登录 token
- 首次使用：复制 `eval_config.example.yaml` 为 `eval_config.yaml` 并按需填写

## 1. 环境自检（不调 LLM，不花钱）

```bash
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_common.py
```

## 2. 运行评估

```bash
# 全量评估（默认三大指标）
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py

# 冒烟（前 3 题，花小钱验证链路）/ 限题数
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --quick
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --limit 5

# 单指标
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --metrics faithfulness
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --metrics faithfulness,context_relevance

# 换被测模型 / 换评审模型
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --model glm --judge-model kimi

# 低 RPM 厂商节流（Kimi RPM=3 用 21，GLM 用 3）
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --throttle 21

# 复用历史结果仅重新评分（调 prompt.py / 换 judge 后不重跑 RAG，不花被测模型的钱）
.venv/Scripts/python backend/scripts-dev/rag-eval/eval_ragas.py --reuse results/ragas_eval_xxx.json
```

| 参数 | 说明 |
| --- | --- |
| --questions | 问题集：路径或文件名子串；缺省用 questions/ 排序第一个 |
| --model | 被测 LLM 子串切换（覆盖 yaml llm.model_filter） |
| --judge-model | 评审 LLM 子串切换（覆盖 judge.model_filter） |
| --metrics | 逗号分隔指标子集，默认全部 |
| --quick / --limit | 前 3 题 / 前 N 题 |
| --reuse <json> | 复用历史 RAG 产物仅重新评分 |
| --throttle <秒> | 全局 HTTP 最小间隔（低 RPM 厂商用） |

## 3. 首次运行会发生什么

1. 自动建知识库 `RAGEVAL-RAG-TEST`，上传 `docs_dir`（默认 `../bench/docs`）下全部
   .txt 并向量化（Embedding 真实调用；本地 bge 零成本）
2. 自动创建 `[RAGEVAL] simple_rag` Agent
3. 复跑时文档已向量化则直接复用；Agent 每次按 yaml 重置检索参数

## 4. 结果 JSON 结构

```
{
  "meta": { ... },        模型/评审模型/embedding/KB/检索参数/token（RAG 与 judge 分列）/时间
  "summary": [...],       每题三指标分数表
  "mean": [...],          均值（仅统计有效题）
  "detail": [ ... ]       每题明细：answer、citations 完整切片、
                          指标中间产物（statements/verdicts、反生成问题及相似度、
                          提取关键句与未匹配句）——调试 prompt 必看
}
```

## 5. 结果解读建议

- faithfulness 低：换更强生成模型 / 检查 prompt（答案是否在编造）
- answer_relevance 低：答案冗余、答非所问或跑题（检查系统提示词）
- context_relevance 低：召回冗余大 → 降 top_k / 提 score_threshold / 开 Rerank
- 指标对比用法：改检索参数（top_k / MQE / HyDE / Rerank）后重跑，比 mean 变化；
  用 `--reuse` 可在换 judge 或调 prompt 后只重评分（省被测调用费用）

## 6. 注意事项

- 真实调用 LLM API 会产生费用：每题约 4~6 次 judge 调用 + 被测链路 1~4 次调用
- 评审 LLM 建议用与被测不同的强模型，避免自评偏置（论文用 gpt-3.5-turbo-16k）
- LLM 输出 JSON 解析失败时该指标记 `-`，可在 detail.note 查看原因
- 调 prompt 后用 `--reuse` 重评历史结果即可对比，无需重跑 RAG
