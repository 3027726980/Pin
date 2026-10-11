<div align="center">

# Pin

**Pin it. It works.**

企业自托管、零代码嵌入的 AI Agent 平台 —— 一行 `<script>` 嵌入网页，浮窗对话。

后端 FastAPI · 前端 Vue 3 · LangChain Agent 编排 · pgvector 向量检索

</div>

---

## 目录

- [项目简介](#项目简介)
- [核心特性](#核心特性)
- [技术栈](#技术栈)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [功能指南](#功能指南)
  - [知识库与文档处理](#知识库与文档处理)
  - [模型配置](#模型配置)
  - [Agent 类型](#agent-类型)
  - [意图路由（降本提速）](#意图路由降本提速)
  - [内置推理工具 plan / reflect](#内置推理工具-plan--reflect)
  - [工具注册体系（新增工具 = 一个文件）](#工具注册体系新增工具--一个文件)
  - [对话与流式输出](#对话与流式输出)
  - [会话与记忆](#会话与记忆)
  - [网页嵌入（Widget）](#网页嵌入widget)
  - [公开接口与嵌入治理](#公开接口与嵌入治理)
  - [日志体系](#日志体系)
- [API 概览](#api-概览)
- [测试](#测试)
- [部署](#部署)
- [开发指南](#开发指南)
- [路线图](#路线图)
- [License](#license)

---

## 项目简介

Pin 是一个**企业自托管**的 AI Agent 平台：

- **零代码嵌入**：在任意网页插入一行 `<script>`，即可获得一个浮窗 AI 助手
- **知识库问答**：上传文档 → 解析/清洗/分块/向量化 → 基于检索增强生成（RAG）回答，回答附带可点击的引用来源
- **可编排 Agent**：简单 RAG Agent（绑定知识库直接问答）与综合 Agent（工具注册、LLM 自主决策、任务规划与反思）
- **厂商无关**：OpenAI 兼容协议统一接入，DeepSeek / Kimi / 通义千问 / 智谱等零代码接入；本地 Embedding 模型开箱即用

## 核心特性

| 能力 | 说明 |
|------|------|
| 🔐 完整认证 | JWT（Access 30min / Refresh 7天）+ jti 白名单即时失效 + 令牌轮转 |
| 📚 文档处理链路 | 上传 → 解析（PDF/Office/Markdown/纯文本）→ 清洗 → 递归分块 → 向量化 → pgvector 检索 |
| 🔍 检索增强 | MQE、HyDE、Rerank 独立配置 off / auto / always，自动策略按原始召回和预算决策 |
| 🤖 双 Agent 类型 | `simple_rag`（知识库直答）+ `general`（工具注册、LLM 自主决策） |
| ⚡ 意图路由 | 简单问题零工具直接回答（省 token / 降延迟），复杂问题完整 ReAct 循环 |
| 🧠 图编排 | 配置化意图 → 可选规划 → 主 Agent → 可选核验与修订 |
| 🧩 工具注册体系 | 新增工具 = 一个文件（自动发现注册 + Schema 驱动前端动态表单） |
| 🏭 厂商协议注册表 | OpenAI 兼容协议统一分发，新增厂商 = config.yaml 加一段配置 |
| 📡 SSE 流式对话 | AgentEvent v2，模型/工具进度、阶段耗时、首答案 Token 与可靠引用 |
| 🧠 多轮记忆 | LangGraph checkpoint 持久化 + 长会话自动总结 |
| 💬 网页嵌入 | 独立构建的 widget.js（Shadow DOM 隔离），API Key 鉴权 + 域名白名单 + 限流 |
| 🗂 日志体系 | 日期目录轮转、脱敏、结构化 Trace 查询与中文完整链路详情 |

## 技术栈

| 层级 | 选型 |
|------|------|
| 后端 | Python ≥ 3.12 · FastAPI · SQLAlchemy 2.0（async）· uvicorn |
| Agent 编排 | LangChain 1.x `create_agent` · LangGraph checkpoint（PostgreSQL） |
| 数据库 | PostgreSQL + pgvector |
| 向量化 | sentence-transformers（本地 bge-small-zh-v1.5）+ OpenAI 兼容 Embedding API |
| LLM 调用 | openai SDK（AsyncOpenAI），协议注册表分发 |
| 前端 | Vue 3 + TypeScript + Vite 6 · Naive UI · Pinia · Vue Router 4 |
| 文档解析 | PyMuPDF · markitdown · 纯文本 |

## 快速开始

### 环境要求

| 依赖 | 版本 | 说明 |
|------|------|------|
| Python | ≥ 3.12 | 后端 |
| PostgreSQL | ≥ 14 | 需启用 `pgvector` 扩展 |
| Node.js | ≥ 18 | 前端 |
| uv | 最新 | 推荐（可选，也可用 venv + pip） |

### 1. 准备数据库

```sql
-- 创建数据库（需已安装 pgvector 扩展）
CREATE DATABASE pin_dev;
```

### 2. 后端启动

```bash
# 安装依赖（uv，推荐）
uv sync

# 或使用传统 venv
python -m venv .venv
.venv/Scripts/activate        # Windows
pip install -e .

# 准备配置文件（重要：config.yaml 不随仓库提交，需手动创建）
cp backend/config.example.yaml backend/config.yaml   # 如无 example 文件，参考下方【配置说明】创建

# 启动（Windows 必须带 --reload，原因见【部署-注意事项】）
uvicorn backend.main:app --reload --port 8000
```

启动成功后会：

- 自动建表（lifespan 初始化）
- 自动播种管理员账号与默认模型配置（来自 config.yaml）
- Swagger 文档：<http://localhost:8000/docs>

> **默认管理员**：`admin / admin123`（生产环境务必通过环境变量 `ADMIN_USERNAME` / `ADMIN_PASSWORD` 修改）

### 3. 前端启动

```bash
cd frontend
npm install
npm run dev        # → http://localhost:8001（/api 已代理到 8000）
```

### 4. 体验流程

1. 登录 `admin / admin123`
2. **模型配置**（设置 → 模型配置）：创建 LLM 配置（如 DeepSeek）与 Embedding 配置
3. **知识库**：新建知识库 → 上传文档 → 预览清洗/切片 → 保存策略并处理至向量化；是否自动处理由知识库开关控制
4. **Agent**：创建 simple_rag（绑定知识库）或 general（配置工具）→ 进入对话

## 配置说明

后端全部配置集中在 `backend/config.yaml`（**已被 .gitignore 忽略，不会提交**），通过 `settings.a.b.c` 点号访问，敏感项可用环境变量覆盖：

```yaml
# 核心配置结构（完整结构以本地 config.yaml 为准）
app:
  name: Pin
  version: 0.1.0

database:
  url: postgresql+asyncpg://postgres:密码@localhost:5432/pin_dev   # SQLAlchemy 异步连接
  pool_size: 5
  max_overflow: 10

checkpoint:
  url: postgresql://postgres:密码@localhost:5432/pin_dev            # LangGraph checkpoint（psycopg 格式）
  keep_rounds: 5                                                     # 每会话保留最近 N 轮快照
  summarization:
    enabled: true                                                    # 长会话自动总结
    trigger_message_count: 20
    keep_message_count: 10

jwt:
  secret_key: change-me-in-production    # 生产必须通过 JWT_SECRET_KEY 环境变量覆盖
  access_token_expire: 30                # 分钟
  refresh_token_expire: 7                # 天

admin:
  username: admin
  password: admin123                     # 生产用 ADMIN_USERNAME / ADMIN_PASSWORD 覆盖

embedding:
  max_dimension: 4096                    # 向量维度（小模型零填充）

tools:
  default_top_k: 5
  default_score_threshold: 0.3
  default_mqe_enabled: false
  default_hyde_enabled: false
  default_mqe_query_count: 3
  default_rerank_enabled: false
  rerank:
    factor: 5

intent:                                  # 意图路由（general Agent）
  simple_max_length: 30                  # 规则判 simple 的最大消息长度（超过升级 LLM 兜底）
  simple_history_limit: 20
  simple_context_max_chars: 1500
  classify_temperature: 0.2

model_types:                             # 模型类型定义（1=Embedding 2=LLM 3=Rerank）
protocols:                               # 协议注册表（openai / dashscope）
preset_providers:                        # 预设厂商（每个厂商声明 protocol + base_url）
preset_models:                           # 预设模型（播种到 model_providers / model_types / default_model_config）

local_models:                            # 本地模型（Embedding / Rerank）
  embedding:
    model_name: bge-small-zh-v1.5
  rerank:
    model_name: bge-reranker-v2-m3

logging:
  dir: logs
  level: INFO
```

### 环境变量覆盖

| 变量 | 覆盖项 |
|------|--------|
| `JWT_SECRET_KEY` | jwt.secret_key |
| `ADMIN_USERNAME` / `ADMIN_PASSWORD` | 初始管理员账号 |
| `CHECKPOINT_URL` | checkpoint.url |
| `CHECKPOINT_KEEP_ROUNDS` | checkpoint.keep_rounds |
| `LOG_DIR` | logging.dir |

## 功能指南

### 知识库与文档处理

1. **创建知识库**：知识库页面 → 新建（选择 Embedding 模型配置）
2. **上传文档**：支持 PDF / Word / Office / Markdown / 纯文本，可批量多选；按知识库的自动处理开关决定是否后台入库，也可先预览、调整策略后手动处理。前端轮询进度，失败显示原因。
3. **处理链路**（每个文档独立状态机）：

```
上传 → 解析（is_parsed）→ 清洗（is_cleaned）→ 分块（is_chunked）→ 向量化（is_vectorized）
状态：-1=失败 0=未完成 1=已完成 2=进行中；失败原因存 last_error
```

> 自动处理开关归知识库；系统设置控制新建默认值和处理并发。文件策略可继承知识库或独立覆盖清洗/切片参数。保存策略不自动重建索引，完整处理成功后才替换旧索引。
> 删除知识库/文档时会级联软删其切片与向量

4. **检索增强**（Agent / RAG 工具独立配置 `off | auto | always`；auto 结合原始召回、问题特征与预算决策，旧 enabled 字段兼容映射 off / always）：

| 增强 | 作用 | 额外消耗 |
|------|------|----------|
| MQE（多查询扩展） | LLM 将问题改写为多个子问题多路检索，提升召回 | LLM 调用 + 多次向量化 |
| HyDE（假设文档嵌入） | LLM 生成假设回答文档作为检索线索 | LLM 调用 + 一次向量化 |
| Rerank 精排 | 粗召回 top_k×factor → 精排 top_k | Rerank 模型调用 |

### 模型配置

设置 → 模型配置，支持三类模型：

| 类型 | 用途 | 说明 |
|------|------|------|
| Embedding（type=1） | 文档/查询向量化 | 本地 bge-small-zh-v1.5 或 OpenAI 兼容 API |
| LLM（type=2） | 对话/总结/增强 | 任意 OpenAI 兼容厂商，`base_url` 可覆盖 |
| Rerank（type=3） | 检索精排 | 本地 bge-reranker 或 API |

**厂商协议注册表**：每个厂商在 config.yaml 声明 `protocol`（如 `openai`），同一协议共享一个实现。新增 OpenAI 兼容厂商 = config.yaml 加一段配置，**零代码改动**。

### Agent 类型

| 类型 | 存储 | 能力 | 适用 |
|------|------|------|------|
| `simple_rag` | simple_rag_agents | 固定绑定一个知识库，每轮强制先调用 RAG 工具再回答 | 客服问答、制度查询 |
| `general` | general_agents | 工具注册（rag 等）+ LLM 自主决策多轮调用 | 复杂任务、多知识库、需要规划反思的场景 |
| `workflow` | （预留） | — | — |

- **simple_rag**：绑定字段转换为 `rag` 工具配置，与 general 共用 `create_agent`、工具日志、引用收集和自动 checkpoint。`RagFirstMiddleware` 在本轮尚无 RAG 工具结果时强制选择 `rag`，结果返回后恢复自主生成；空结果也由 Agent 回答，提示词要求明确资料不足。供应商必须支持指定 `tool_choice`，真实兼容性仍待验收。
- **general**：创建时勾选工具（见工具注册体系），对话由 LLM 自主决定调用哪些工具、调用几轮（LangGraph 多轮）

### 意图路由（降本提速）

general Agent 可开启「意图路由」（Agent 级开关，默认关闭）：

```
用户提问
  │
  ▼
① 意图识别（Agent 级规则引擎 → 未命中则 LLM 兜底分类）
  ├── simple  → 零工具直接回答（省 token / 降延迟）
  └── general → 可选 plan → 主 Agent 工具循环 → 可选 verify / revision
```

- **规则引擎**：Agent 级自定义（预设模板 + 可编辑），支持 `keyword` / `regex` / `length` 三种规则，按优先级从小到大执行、命中即判定
- **保守原则**：指向轻量路由的 keyword 必须覆盖整句（忽略标点、空白与大小写），业务路由仍为包含匹配。纯“你好！”直接轻量回答；“你好，我想了解一点这个课程的事情”继续业务规则或 LLM 分类，不再被问候截走。现有规则无需重新保存；自定义 regex / length 语义不变。
- **长度保护**：规则判 simple 但超过 `intent.simple_max_length`（默认 30 字）仍升级 LLM 兜底。
- **LLM 兜底**：结合最近语义历史和业务工具选择 `intent.categories` 中的类别码；动态 Pydantic 枚举校验输出，再映射到 `simple/general` 执行路由及规划、核验策略。`complex` 可作为类别码，执行路由本身仍只有两种；分类失败降级到 general 路由。
- **simple 档**：零工具直答不等于执行知识检索；业务追问需结合上下文分类，不保证仅靠旧上下文回答准确。
- 对话页气泡顶部会显示 `⚡ 轻量模式` / `🛠 完整模式` 标签

### 内置推理工具 plan / reflect

当前规划与核验由 AgentGraph 节点执行。配置类别的 `use_plan/use_reflect` 与 Agent 的 `plan_enabled/reflect_enabled` 共同决定是否执行；不向主 Agent 注册 plan/reflect 工具。主答案先流式输出，需要时再核验，明确要求修订才进入 revision。

| 工具 | 作用 | 说明 |
|------|------|------|
| `plan` | 为复杂任务制定分步执行计划 | 图节点输出规划，主 Agent 参考执行 |
| `reflect` / verify | 核验已经生成的主答案 | 需要时触发 revision；旧 draft/reflect 方法未接入当前执行图 |

对话页展示执行过程；详细规划、核验结果和模型/工具诊断通过「查看完整链路日志」查看。

### 工具注册体系（新增工具 = 一个文件）

**核心机制**：`tools/agent/` 目录扫描 + `BaseTool.__init_subclass__` 自动注册 + 参数 Schema 驱动前端动态表单。

#### 新增工具步骤

```bash
# 1. 在 backend/tools/agent/ 下新建 xxx.py（只需这一个文件）
```

```python
"""Agent 工具：xxx（示例）"""
from backend.tools.common.base import BaseTool


class XxxTool(BaseTool):
    """新工具示例"""

    type = "xxx"                       # 工具类型（注册表 key，全局唯一）
    description = "工具描述（给 LLM 判断是否调用）"
    name_ref_keys = {}                 # 需要补全名称的配置字段（如 {"kb_id": "kb_name"}）
    # builtin = True                   # 内置工具标记（不进入前端工具列表）

    # 参数 Schema（前端动态表单渲染，新增工具无需改前端）
    param_schema: list[dict] = [
        {"key": "query", "label": "查询词", "type": "string", "required": True,
         "placeholder": "请输入查询词"},
        {"key": "limit", "label": "返回条数", "type": "number",
         "default": 5, "min": 1, "max": 50},
        {"key": "enabled", "label": "启用开关", "type": "boolean", "default": False},
        {"key": "target", "label": "目标", "type": "select", "required": True,
         "source": "my_targets"},      # select 选项来源（配合 fetch_options）
    ]

    @staticmethod
    async def fetch_options(db, user, source: str) -> list[dict]:
        """select 参数动态选项（仅需要时覆写）：返回 [{label, value}]"""
        if source == "my_targets":
            return [{"label": "选项A", "value": "a"}]
        return []

    @staticmethod
    async def validate_config(db, user, config: dict, **kwargs) -> None:
        """配置校验（创建/编辑 Agent 时调用），失败 raise HTTPException"""
        return None

    @staticmethod
    def build_langchain(db, user, config: dict, **kwargs):
        """构建 LangChain 工具（对话时调用），返回 @tool 对象"""
        from langchain_core.tools import tool

        @tool
        async def xxx(query: str) -> str:
            """给 LLM 看的工具签名与描述"""
            return "工具执行结果"
        return xxx

    # execute 可供工具内部复用；simple_rag 也通过 build_langchain 构建的工具执行
```

```bash
# 2. 保存文件即生效（tool-defs 请求前自动目录同步，前端刷新即可见）
# 3. 验证
curl http://localhost:8000/api/v1/agents/tool-defs -H "Authorization: Bearer <token>"
# → 新工具自动出现（含参数 Schema 与动态选项），前端表单自动渲染

> **热更新语义**：新增/删除工具文件**即时生效**（tool-defs 每次请求前重新扫描磁盘目录，无需重启后端，前端点「刷新」即可见）；但**修改已有工具文件的代码**（改 description / 参数 / 逻辑）需要**重启后端**（Python 模块缓存机制，改文件不会自动重载）。
```

#### 参数类型

| type | 前端控件 | 说明 |
|------|----------|------|
| `string` | 输入框 | 单行文本 |
| `textarea` | 多行输入 | 长文本 |
| `number` | 数字输入 | 支持 min / max / step |
| `boolean` | 开关 | 布尔值 |
| `select` | 下拉选择 | 选项由后端 `fetch_options` 动态提供 |

#### 健壮性（不规范文件处理）

| 场景 | 日志 | 行为 |
|------|------|------|
| 非 .py 文件 | — | 自动忽略 |
| import 报错的坏文件 | `ERROR` | 跳过该文件，应用正常启动 |
| 未实现抽象方法的类 | `WARNING` | 拒绝注册 |
| type 重复 | `WARNING` | 后者覆盖 |
| 正常注册 | `INFO` | 启动日志输出注册清单 |

### 对话与流式输出

```
POST /api/v1/agents/{agent_id}/chat
```

请求体：`{ "message": "...", "conversation_id": null, "stream": true, "debug": false }`

流式 SSE 使用 AgentEvent v2；旧 intent / delta / done 等为历史协议，不用于当前事件解析：

| 事件 | 字段 | 说明 |
|------|------|------|
| `turn.started` | `trace_id/turn_id` | 本轮开始 |
| `stage.started/progress/completed/failed` | `stage/stage_id/status/detail/duration_ms` | 意图、MQE、HyDE、模型轮、工具轮等阶段 |
| `answer.delta` | `content` | 答案增量；不输出隐藏推理内容 |
| `answer.revision_started` | `detail` | 答案修订开始 |
| `citations.completed` | `citations/citation_bindings` | 可验证来源与标记绑定 |
| `turn.completed/failed/cancelled` | `duration_ms/detail` | 唯一终态；服务器首答案耗时用于最终校准 |

新回答使用稳定 `[S#]` 与 `citation_bindings`，仅展示服务端验证的来源；旧 `[N]` 保留兼容。管理端接收 public/debug 事件，Widget 仅接收 public。

`debug` 请求字段仅为旧客户端兼容。后端始终采集安全 Trace，聊天页使用「查看完整链路日志」作为诊断入口，已移除冗余 Debug 开关。准备阶段保留在完整链路内，常规进度不展示其细节。详情默认中文字段和结构化结果，原始 JSON 折叠；连续 answer.delta 在 UI 合并，但原始日志保留。聊天内查看链路打开抽屉，详情每 2 秒刷新至终态。页面内跨路由保留进行中的聊天，浏览器刷新不支持 SSE 重连。

模型首输出与首答案 Token 是不同指标：Agent 可能先选择/执行工具，再生成答案；阶段进度不代表实际答案延迟已降低。模型耗时包含上游等待，不暴露或推断隐藏思维链。

### 会话与记忆

- 会话由服务端管理：`conversation_id` 缺省时自动创建
- **checkpoint 记忆**：LangGraph 持久化，新 thread 为 `memory_v2:{conversation_id}`，namespace 为空；前端继续使用原 conversation_id。首次访问按需迁移旧 thread 消息，不恢复旧待执行任务。
- **长会话总结**：SummarizationMiddleware 自动压缩（触发/保留条数可配）。轻量直答也走零工具 `create_agent`，通过 `SimpleContextMiddleware` 投影模型输入，框架自动保存原始消息。
- **展示历史**：`conversations.messages` 独立保存页面历史和引用；记忆修复使用公开图状态 API，不手写 checkpoint 版本。当前会话锁只覆盖本进程记忆服务更新，不保证多进程整轮互斥。
- 会话列表 / 历史消息 / 删除：`/api/v1/conversations` 系列接口
- 匿名访客（widget）：会话归属 `client_id`

### 网页嵌入（Widget）

1. **构建**：

```bash
cd frontend
npm run build:widget     # 产出单文件 backend/static/widget/widget.js
```

2. **生成 API Key**：Agent 列表 → 嵌入设置 → 生成 API Key（可设置域名白名单 / 限流 / 匿名会话保留天数）

3. **嵌入任意网页**：

```html
<script src="https://你的域名/widget/widget.js"
        data-agent-id="<agent_id>"
        data-api-key="<api_key>"></script>
```

浮窗对话由 Shadow DOM 隔离样式，支持：

- 公开接口鉴权（X-API-Key）
- 域名白名单（`allowed_domains`，空 = 不限制）
- 限流（`rate_limit_per_min`，默认 60 次/分钟）
- 匿名会话自动清理（`anonymous_retention_days`）

### 公开接口与嵌入治理

```
POST   /api/v1/public/auth/login                访客登录（换取访客 token）
POST   /api/v1/public/agents/{id}/chat          访客对话（X-API-Key 鉴权）
GET    /api/v1/public/conversations             访客会话列表
POST   /api/v1/public/conversations             创建访客会话
DELETE /api/v1/public/conversations/{id}        删除访客会话
GET    /api/v1/public/conversations/{id}/messages  访客历史消息
```

### 日志体系

后端日志输出到 `logs/YYYY-MM-DD/`（config.yaml `logging.dir`，环境变量 `LOG_DIR` 可覆盖），包含日期模板文本日志与结构化 JSONL：

| 文件 | 内容 |
|------|------|
| `http.log` | HTTP 请求链路（方法/路径/状态/耗时/IP） |
| `llm.log` | LLM 调用链路（模型/耗时/输出长度/错误） |
| `sql.log` | SQL 执行（调试用） |
| `error.log` | 异常堆栈 |
| `app.log` | 应用业务日志 |

上述文本日志实际文件名默认为 `YYYY-MM-DD-模块.log`。结构化文件包括 `access.jsonl`、`agent-trace.jsonl`、`llm.jsonl`、`tool.jsonl`，通过 request_id / trace_id / turn_id 关联。仅超级管理员可通过 `/api/v1/debug/agent-traces` 查询、查看及导出脱敏链路。容器日志与应用文件日志独立轮转；应用 Trace 必须保留 `pin-logs` 卷。

## API 概览

```
# 认证
POST   /api/v1/auth/login                       管理员登录（JWT）
POST   /api/v1/auth/refresh                     刷新 Token（轮转）

# 知识库
GET/POST /api/v1/knowledge-bases                列表 / 创建
GET/PUT/DELETE /api/v1/knowledge-bases/{id}     详情 / 编辑 / 软删除
POST   /api/v1/knowledge-bases/batch            批量操作
POST   /api/v1/knowledge-bases/{id}/files       上传文件
GET    /api/v1/knowledge-bases/{id}/files       文件列表
DELETE /api/v1/knowledge-bases/{id}/files/{doc} 删除文件
POST   /api/v1/knowledge-bases/{id}/files/batch 批量删除
POST   /api/v1/knowledge-bases/{id}/parse|chunk|vectorize   文档处理链路（含 /status）

# 模型配置
CRUD   /api/v1/settings/user-model-config       模型配置管理（LLM/Embedding/Rerank）

# Agent
GET/POST /api/v1/agents                         列表（type 筛选）/ 创建
GET/PUT/DELETE /api/v1/agents/{id}              详情 / 编辑 / 删除
POST   /api/v1/agents/batch                     批量操作
GET    /api/v1/agents/defaults                  默认配置
GET    /api/v1/agents/tool-defs                 工具定义（参数 Schema + 动态选项）
POST   /api/v1/agents/{id}/chat                 对话（stream 可选，SSE 流式）
GET/POST/PUT/DELETE /api/v1/agents/{id}/api-keys  嵌入 API Key 管理

# 会话
CRUD   /api/v1/conversations                    会话管理 + 历史消息

# 公开接口（访客）
/api/v1/public/*                                见【公开接口与嵌入治理】

# 系统
GET    /api/v1/settings/protocols               协议列表
GET/PUT /api/v1/settings/{key}                  系统设置
CRUD   /api/v1/providers                        厂商管理
```

完整接口文档：后端启动后访问 <http://localhost:8000/docs>（Swagger UI）。

## 测试

```bash
# 后端测试（pytest，含 API / 记忆 / 工具 / 检索增强等）
.venv/Scripts/python -m pytest tests/ -v

# 前端类型检查 + 构建
cd frontend
npm run build
```

## 部署

> 当前版本（v0.1）为开发/内测形态，生产部署建议结合 Docker（路线图中规划）。以下为手动部署要点。

### 生产部署要点

1. **环境变量覆盖敏感配置**：

```bash
export JWT_SECRET_KEY="<随机强密钥>"
export ADMIN_USERNAME="admin"
export ADMIN_PASSWORD="<强密码>"
```

2. **启动后端**（生产建议 gunicorn + uvicorn worker）：

```bash
pip install gunicorn
gunicorn backend.main:app -k uvicorn.workers.UvicornWorker -w 4 -b 0.0.0.0:8000
```

3. **构建前端**：

```bash
cd frontend
npm run build
# 产物在 frontend/dist/，用 Nginx 托管并反向代理 /api → 后端
```

4. **构建 widget**：

```bash
npm run build:widget    # 产出 backend/static/widget/widget.js（后端 /widget 静态托管）
```

### 注意事项

- **Windows 必须 `--reload` 启动**：uvicorn 0.21 在 Windows 上仅 `use_subprocess=True`（reload 模式）时切换 SelectorEventLoop，否则 psycopg async 会报 `ProactorEventLoop` 不兼容（本项目已在 main.py 设置事件循环策略，但 uvicorn 在 import 应用前创建循环，故必须 --reload）
- **连接池**：已启用 `pool_pre_ping`（防止 PostgreSQL 断开空闲连接后复用失效连接）
- **配置文件**：`backend/config.yaml` 不入库，部署时需自行创建（参考【配置说明】）
- **生产禁止**使用默认 JWT 密钥 `change-me-in-production`

## 开发指南

### 项目结构

```
pin/
├── backend/
│   ├── main.py                 # 应用入口：建表 + 播种 + 统一异常处理 + 路由注册
│   ├── config.yaml             # 全部配置（Git 忽略，本地创建）
│   ├── core/                   # 基础设施（config / database / security / constants）
│   ├── models/                 # ORM 模型（文件名 = 表名）
│   ├── schemas/                # Pydantic 请求/响应
│   ├── repositories/           # 数据访问层（纯 SQL，不管业务）
│   ├── services/               # 业务逻辑层（协调 Repository + 规则）
│   ├── tools/                  # 工具注册体系（自动发现 + Schema 驱动）
│   │   ├── common/base.py      # BaseTool 抽象基类
│   │   └── agent/              # 工具目录（rag / plan / reflect）
│   ├── api/v1/                 # 接口层（薄）
│   ├── sql/                    # 建表参考 + 增量迁移（001~020）
│   └── static/widget/          # widget.js 构建产物
├── frontend/
│   ├── src/views/              # 页面（dashboard / knowledge / agent / settings）
│   ├── src/widget/             # 浮窗组件源码
│   └── vite.widget.config.ts   # widget 独立构建
├── dev-docs/                   # 设计与接口文档（Git 忽略）
└── tests/                      # pytest 测试
```

### 分层规范

```
Router（薄）→ Service（业务）→ Repository（SQL）→ DB
```

| 层 | 职责 | 禁止 |
|----|------|------|
| `api/v1/*.py` | 解析请求、调 Service、返回统一响应 | 不写业务逻辑 / SQL |
| `services/*.py` | 业务规则、多步协调、异常转换 | 不写 SQL、不直接访问模型 |
| `repositories/*.py` | 纯 SQL 访问 | 不写业务、不管事务 |

所有接口返回统一结构：`{"code": 200, "message": "ok", "result": {...}}`

### 新增模型厂商

```yaml
# config.yaml：加一段配置即可，零代码改动
preset_providers:
  - name: my_provider
    protocol: openai              # 复用 OpenAI 兼容实现
    base_url: https://api.example.com/v1
    models:
      - model_name: my-model
        model_type: 2             # 1=Embedding 2=LLM 3=Rerank
```

新增协议（非 OpenAI 兼容）：实现一个类注册到 `backend/services/llm.py` 的 `LLM_IMPLEMENTATIONS`。

### 数据库迁移

```bash
# 新增表/字段 → 三个步骤：
# 1. backend/sql/migrations/0XX_xxx.sql（编号递增，历史迁移不修改）
# 2. backend/models/ 建 ORM 类 + __init__.py 导出
# 3. backend/sql/init.sql 同步最终结构
```

### Git 约定

- 分支：`dev-LHF`（开发）→ `main`（合入）
- Commit 前缀：`feat:` / `fix:` / `refactor:` / `docs:` / `chore:`
- 敏感文件（config.yaml / 上传文件 / 日志 / 模型缓存）已加入 .gitignore

## 路线图

| Phase | 内容 | 状态 |
|-------|------|------|
| 1 | 认证基础设施 | ✅ |
| 2 | 知识库 CRUD + 上传 + 前端 | ✅ |
| 3 | 文档处理链路 + 模型配置 | ✅（含上传自动处理，2026-08-24） |
| 4 | Agent CRUD + RAG 对话 + 意图路由 + 工具体系 | ✅ |
| 5 | 浮窗嵌入组件（widget.js） | ✅ |
| 6 | 联调 + Docker 部署 | 🔄 Dockerfile/Compose 已有，近期配置更新与 GPU/生产验收待实测 |
| — | 工具生态（web_search 等更多内置工具） | ⏳ |
| — | workflow Agent（强制按计划执行） | ⏳ |
| — | 意图路由数据埋点（simple/general 占比统计） | ⏳ |

## License

本项目目前**未指定开源协议**。如需正式开源，请联系作者补充 LICENSE 文件。
