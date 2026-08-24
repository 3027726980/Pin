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
- **知识库问答**：上传文档 → 自动解析/分块/向量化 → 基于检索增强生成（RAG）回答，回答附带可点击的引用来源
- **可编排 Agent**：简单 RAG Agent（绑定知识库直接问答）与综合 Agent（工具注册、LLM 自主决策、任务规划与反思）
- **厂商无关**：OpenAI 兼容协议统一接入，DeepSeek / Kimi / 通义千问 / 智谱等零代码接入；本地 Embedding 模型开箱即用

## 核心特性

| 能力 | 说明 |
|------|------|
| 🔐 完整认证 | JWT（Access 30min / Refresh 7天）+ jti 白名单即时失效 + 令牌轮转 |
| 📚 文档处理链路 | 上传 → 解析（PDF/Office/Markdown/纯文本）→ 递归分块 → 向量化 → pgvector 检索 |
| 🔍 检索增强 | MQE 多查询扩展、HyDE 假设文档、Rerank 精排（均可独立开关） |
| 🤖 双 Agent 类型 | `simple_rag`（知识库直答）+ `general`（工具注册、LLM 自主决策） |
| ⚡ 意图路由 | 简单问题零工具直接回答（省 token / 降延迟），复杂问题完整 ReAct 循环 |
| 🧠 内置推理工具 | plan（任务规划）+ reflect（答案反思），LLM 自主编排 |
| 🧩 工具注册体系 | 新增工具 = 一个文件（自动发现注册 + Schema 驱动前端动态表单） |
| 🏭 厂商协议注册表 | OpenAI 兼容协议统一分发，新增厂商 = config.yaml 加一段配置 |
| 📡 SSE 流式对话 | delta / citations / plan / reflect / intent 事件，打字机体验 |
| 🧠 多轮记忆 | LangGraph checkpoint 持久化 + 长会话自动总结 |
| 💬 网页嵌入 | 独立构建的 widget.js（Shadow DOM 隔离），API Key 鉴权 + 域名白名单 + 限流 |
| 🗂 日志体系 | 分文件日志（http / llm / sql / error）+ 统一格式化 + 轮转 |

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
3. **知识库**：新建知识库 → 上传文档 → 解析 → 分块 → 向量化
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
2. **上传文档**：支持 PDF / Word / Office / Markdown / 纯文本，可批量上传
3. **处理链路**（每个文档独立状态机）：

```
上传 → 解析（is_parsed）→ 分块（is_chunked）→ 向量化（is_vectorized）
```

4. **检索增强**（知识库/Agent 级独立开关，按需开启以节省 token）：

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
| `simple_rag` | simple_rag_agents | 固定绑定一个知识库，代码控制检索 → 回答 | 客服问答、制度查询 |
| `general` | general_agents | 工具注册（rag 等）+ LLM 自主决策多轮调用 | 复杂任务、多知识库、需要规划反思的场景 |
| `workflow` | （预留） | — | — |

- **simple_rag**：创建时绑定知识库，对话固定走"检索 → 注入引用块 → 生成"；无命中时短路返回"知识库中没有相关信息"
- **general**：创建时勾选工具（见工具注册体系），对话由 LLM 自主决定调用哪些工具、调用几轮（LangGraph 多轮）

### 意图路由（降本提速）

general Agent 可开启「意图路由」（Agent 级开关，默认关闭）：

```
用户提问
  │
  ▼
① 意图识别（Agent 级规则引擎 → 未命中则 LLM 兜底分类）
  ├── simple  → 零工具直接回答（省 token / 降延迟）
  └── general → 完整 ReAct 循环（LLM 自主调用工具 / 规划 / 反思）
```

- **规则引擎**：Agent 级自定义（预设模板 + 可编辑），支持 `keyword` / `regex` / `length` 三种规则，按优先级从小到大执行、命中即判定
- **保守原则**：`simple` 规则保持保守（问候/感谢/闲聊），`general` 规则可放宽（误判代价小）；规则判 simple 但消息超过 `intent.simple_max_length`（默认 30 字）自动升级 LLM 兜底，防"你好，帮我查一下报销制度"被误判
- **LLM 兜底**：无规则命中时低温调用一次分类（`{"intent": "simple"|"general"}`）；分类失败默认走 general（宁多花 token 不答错）
- **simple 档记忆**：历史纯文本化 + 最近一轮检索残留注入，追问场景（"那差旅标准呢"）也能答对
- 对话页气泡顶部会显示 `⚡ 轻量模式` / `🛠 完整模式` 标签

### 内置推理工具 plan / reflect

general Agent 默认注册两个内置推理工具（Agent 级独立开关，无需任何配置）：

| 工具 | 作用 | 说明 |
|------|------|------|
| `plan` | 为复杂任务制定分步执行计划（JSON 步骤数组） | 建议性参考，LLM 在 ReAct 循环中参考执行 |
| `reflect` | 批评性审查答案草稿（完整性/准确性/证据） | LLM 据此修正最终回答 |

对话页会以「📋 执行计划」「🔍 反思建议」折叠面板展示过程。

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

    # execute 仅代码控制场景（如 simple_rag 预检索）需要，纯 LLM 调用型工具可不实现
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

流式 SSE 事件：

| 事件 | 字段 | 说明 |
|------|------|------|
| `intent` | `intent` | 意图判定结果（simple / general，路由开启时） |
| `plan` | `plan` | 规划内容（LLM 调用 plan 工具时） |
| `reflect` | `suggestions` | 反思建议（LLM 调用 reflect 工具时） |
| `delta` | `content` | 回答文本增量（打字机） |
| `citations` | `citations` | 引用来源列表（生成完成后一次推送） |
| `debug` | `debug` | 检索调试信息（request.debug=true 时） |
| `error` | `code/message/suggestion` | 错误（如推理模型 temperature 限制） |
| `done` | — | 结束 |

引用标注：回答中的 `[N]` 可点击，定位展开对应引用来源（仅展示实际引用的条目）。

### 会话与记忆

- 会话由服务端管理：`conversation_id` 缺省时自动创建
- **checkpoint 记忆**：LangGraph 持久化（thread_id = conversation_id），多轮对话自动携带上下文
- **长会话总结**：SummarizationMiddleware 自动压缩（触发/保留条数可配）
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

后端日志按模块分文件输出到 `logs/`（config.yaml `logging.dir`）：

| 文件 | 内容 |
|------|------|
| `http.log` | HTTP 请求链路（方法/路径/状态/耗时/IP） |
| `llm.log` | LLM 调用链路（模型/耗时/输出长度/错误） |
| `sql.log` | SQL 执行（调试用） |
| `error.log` | 异常堆栈 |
| `app.log` | 应用业务日志 |

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
| 3 | 文档处理链路 + 模型配置 | 🔄 后端完成（自动触发异步处理搁置） |
| 4 | Agent CRUD + RAG 对话 + 意图路由 + 工具体系 | ✅ |
| 5 | 浮窗嵌入组件（widget.js） | ✅ |
| 6 | 联调 + Docker 部署 | ⏳ |
| — | 工具生态（web_search 等更多内置工具） | ⏳ |
| — | workflow Agent（强制按计划执行） | ⏳ |
| — | 意图路由数据埋点（simple/general 占比统计） | ⏳ |

## License

本项目目前**未指定开源协议**。如需正式开源，请联系作者补充 LICENSE 文件。
