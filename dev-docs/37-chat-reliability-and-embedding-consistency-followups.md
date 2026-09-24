# 对话可靠性与 Embedding 一致性待办

> 记录时间：2026-09-24
> 状态：待设计、待实施
> 范围：仅记录 2026-09-23 至 2026-09-24 联调中已经确认的问题，不代表本轮已实施。

## 1. 当前已完成的临时处理

- 管理端编辑知识库时已锁定 Embedding 下拉框，并提示“创建后不可修改”。
- Debug 面板已展示 `intent / intent_code`，无检索 Query 时会提示本轮未执行检索。
- 当前轮没有可验证引用时，回答不再保留 `[S#]`；历史 checkpoint 中的展示型来源编号也会在下一轮调用前清理。

上述措施只解决前端误操作和引用展示问题，下面事项仍需后续实施。

## 2. P0：修复手动 checkpoint 缺少 `step`

### 已确认现象

会话先走 `simple`，之后再进入 `general` 时，流式调用可能返回：

```text
LLM 服务调用失败: 'step'
```

### 根因

`ChatService._persist_simple_turn()` 和 `_persist_turn_without_llm()` 会手动创建或更新 LangGraph checkpoint。新 checkpoint 使用空 `metadata`，但当前 LangGraph 恢复执行时会读取 `checkpoint_metadata["step"]`，因此抛出 `KeyError: 'step'`。错误发生在主模型请求之前，却被统一包装成 LLM 调用失败。

### 待修改

- 统一封装手动 checkpoint metadata，至少包含 LangGraph 所需的 `source`、`step`、`parents`。
- 读取旧 checkpoint 时补齐缺失 metadata，兼容已经产生的会话。
- 不直接清空现有 checkpoint，避免丢失会话上下文。
- 增加以下回归测试：
  - 新会话 `simple -> general` 可以继续执行。
  - RAG 无命中手动落 checkpoint 后，下一轮 general 可以继续执行。
  - 旧 checkpoint 缺少 `step` 时能够自动修复。

### 验收标准

- 不再出现 `KeyError: 'step'`。
- 修复前已有会话无需删除即可继续使用。
- checkpoint 中历史 Human/AI 消息保持完整。

## 3. P0：模型参数能力兼容

### 已确认现象

Kimi `kimi-k2.6` 的意图分类先后返回：

```text
invalid temperature: only 1 is allowed for this model
invalid top_p: only 0.95 is allowed for this model
```

### 根因

意图分类目前固定使用 `temperature=0.2`、`top_p=0.9`。现有重试只把 temperature 改成 1，没有同步处理 top_p，因此一次分类会产生两次无效请求，随后才降级为 general。

### 待修改

- 分类、MQE、HyDE、plan、draft、reflect 和主 Agent 统一读取模型配置中的采样参数。
- 将模型参数限制抽象为协议或模型能力配置，避免继续依赖错误字符串逐项重试。
- 对仅允许固定参数的模型，在发出请求前完成参数归一化。
- 增加 Kimi 固定 `temperature/top_p` 的测试，以及普通 OpenAI 兼容模型的回归测试。

### 验收标准

- Kimi 分类不再先产生 400 请求。
- 同一模型在不同调用节点使用一致且合法的参数。

## 4. P0：供应商 RPM 限流治理

### 已确认现象

Kimi 账号组织级限制为 3 RPM。一次完整 general + RAG 对话可能包含：

1. 意图分类；
2. 主 Agent 决定是否调用工具；
3. MQE；
4. HyDE；
5. 工具执行后的最终回答；
6. SDK 对 429 的自动重试。

单轮请求数量可能超过账户上限，最终返回 `rate_limit_reached_error`。当前 MQE/HyDE 会降级，但最终主 Agent 仍可能因 429 失败。

### 待修改

- 增加按供应商/API Key 维度共享的请求节流器，覆盖所有 LLM 调用入口。
- 识别并遵循 `Retry-After`，使用带上限的退避策略，避免多个节点各自立即重试。
- 429 错误通过 SSE 返回 `code=429`，不要统一包装为 502。
- 支持增强模型与主对话模型分离，避免 MQE/HyDE 消耗主模型的低 RPM 配额。
- 对低配额模型提供策略：关闭 MQE/HyDE、优先命中规则免分类、限制复杂编排节点。

### 验收标准

- 并发及连续请求不会形成重试风暴。
- 达到限额时前端收到明确的 429 和可重试提示。
- MQE/HyDE 失败仍能用原始 Query 检索；若最终回答无法调用，不写入空 assistant 消息。

## 5. P1：后端禁止修改知识库 Embedding

### 已确认现象

简历知识库先使用本地 `bge-small-zh-v1.5` 生成 13 条向量，之后知识库配置被改成阿里云 `text-embedding-v1`，但已有文档没有重新向量化。查询向量和文档向量来自不同空间，所有候选均被 `score_threshold=0.3` 过滤，表现为“已经调用 RAG，但引用为 0”。

### 当前临时措施

前端编辑弹窗已禁用 Embedding 下拉框，但 API、脚本或旧版客户端仍可提交 `user_model_config_id / embedding_model / embedding_dimension`。

### 待修改

- `KnowledgeBaseService.update()` 比较新旧 Embedding 配置；发生实际变化时返回 409。
- 提交与当前值相同的字段应兼容通过，避免旧客户端无法编辑其他属性。
- API 文档明确 Embedding 只能在创建知识库时选择。
- 检查被知识库引用的模型配置是否允许修改 provider、model_name、dimension；如果允许，同样可能造成向量空间漂移，应禁止修改关键字段或引入配置版本。
- 为历史错配知识库提供一次性修复方式：恢复原模型，或选择新模型后重新向量化全部文档。

### 长期防线

当前 `embeddings` 表不记录生成该向量时的模型配置。后续可选择：

- 在向量记录或文档处理结果中保存 `embedding_config_id/model/version/dimension` 快照；或
- 保存知识库 Embedding 配置 hash，并在检索前校验当前配置和向量化配置一致。

### 验收标准

- 创建后无法通过前端、API 或脚本修改知识库 Embedding。
- 模型配置变更不能静默影响已生成向量。
- 检索前发现历史错配时返回明确错误，而不是静默返回空结果。

## 6. P1：失败轮次不写入空助手消息

### 已确认现象

`'step'` 或 429 导致流式失败后，会话历史中可能留下 `content=""` 的 assistant 消息，后续上下文和消息计数都会受到污染。

### 待修改

- 区分正常完成、用户中止和异常失败。
- 没有任何有效输出且收到 error 时，不持久化 assistant 消息。
- 如果已经输出部分 delta 后失败，明确保存策略：保留并标记 incomplete，或不写历史；不可继续当成完整回答使用。
- 增加失败流式调用的会话历史回归测试。

## 7. P1：完整模式响应时间优化

### 已确认数据

2026-09-23 日志中，多轮完整模式总耗时约 66～97 秒；单次 GLM 非流式调用约 5～28 秒。主要耗时来自多个 LLM 节点串行执行，而不是数据库 CRUD。

### 待修改

- 为 intent、plan、draft、reflect、主 Agent 首次决策、MQE、HyDE、Embedding、Rerank、最终生成分别记录耗时。
- Debug 面板增加节点耗时，区分首 Token 时间和总耗时。
- 规则明确命中时不调用分类模型。
- 只有 `complex` 才执行 plan/draft/reflect，普通 general 直接进入主 Agent。
- MQE 与 HyDE 在配额允许时评估并行执行；低 RPM 模型优先关闭其中一个或全部关闭。
- 对候选人简历这类固定检索场景，评估使用 `simple_rag` 或“确定性检索后单次生成”，减少 ReAct 的工具选择调用。

### 验收标准

- 日志可以解释一轮对话每个阶段的耗时占比。
- 建立 simple/general/complex 三类基准；优化前后使用相同问题和模型比较。
- 不以关闭检索或牺牲当前轮可验证引用为代价换取速度。

## 8. P2：日志日期轮转核查

### 已确认现象

进程跨过零点后，`2026-09-24 00:02:16` 的日志仍写入 `logs/2026-09-23/2026-09-23-app.log`。需要确认日期目录轮转是否只在进程启动时计算文件名。

### 待修改

- 检查自定义 handler 的日期目录和文件名刷新逻辑。
- 增加跨日轮转测试，确认 app/http/llm/sql 四类日志一致切换。
- 轮转时确保旧文件句柄关闭，不重复注册 handler。

## 9. 建议实施顺序

1. 修复 checkpoint `step`，恢复基本可用性。
2. 修复模型参数兼容，消除无效请求。
3. 实施 RPM 节流及 429 语义化错误。
4. 后端锁定知识库 Embedding，并处理现有错配知识库。
5. 修复失败轮次的空消息持久化。
6. 补齐分阶段耗时后再进行性能优化。
7. 核查日志跨日轮转。

每一项应独立编写回归测试、实施和验收，避免把可靠性修复与性能重构一次性混合提交。
