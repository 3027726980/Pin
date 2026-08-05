# Pin 项目架构文档

> **产品名**: Pin  
> **口号**: Pin it. It works.  
> **定位**: 面向企业自托管的零代码 AI Agent 嵌入平台  
> **版本**: MVP v0.1

---

## 1. 产品概述

Pin 是一个轻量级、零侵入的 AI Agent 平台。企业用户部署后，只需一行 `<script>` 标签即可在自己的 HTML 页面中嵌入智能对话浮窗，为访客提供基于 RAG 知识库的问答服务。

### 核心场景

```
企业部署 Pin → 上传文件构建知识库 → 创建 Agent 配置 → 获取嵌入代码
                                                          ↓
                                              贴入企业网站/后台系统
                                                          ↓
                                          访客通过浮窗与知识库对话
```

---

## 2. 核心数据模型

```
管理员（单账号，MVP）
  │
  ├── 知识库 A ──── 文件1, 文件2, ...（RAG 数据源）
  ├── 知识库 B
  ├── 知识库 C
  │
  ├── Agent X ──── 挂载 [知识库A, 知识库B]  + 配置（prompt/模型/响应模式）
  ├── Agent Y ──── 挂载 [知识库C] + 不同配置
  │
  ├── 浮窗 #1 ──── 链接到 Agent X
  ├── 浮窗 #2 ──── 链接到 Agent Y
```

### 关键关系

| 关系 | 说明 |
|------|------|
| 知识库 ← 文件 | 1:N，文件上传后解析分块入库 |
| Agent ← 知识库 | N:M，Agent 可挂载多个知识库 |
| 浮窗 ← Agent | N:1，多个浮窗可链接同一 Agent |
| 管理员 ← 所有资源 | 1:N，MVP 单管理员拥有全部资源 |

### 预留多租户扩展

```
后续版本：
  管理员 ──── 创建子用户
               ├── 用户A ──── 知识库A（私有）
               ├── 用户B ──── 知识库B（私有）
               └── 共享知识库（管理员分配权限）
```

---

## 3. 系统架构

```
┌─────────────────────────────────────────────────────────────┐
│                     用户浏览器                               │
│  ┌──────────────────┐    ┌──────────────────────────────┐   │
│  │   管理后台          │    │    用户网站                     │   │
│  │   (Vue3 + NaiveUI) │    │  ┌────────────────────────┐  │   │
│  │   localhost:5173   │    │  │ 浮窗 (Vue3 + NaiveUI)    │  │   │
│  │   登录/管理KB/Agent  │    │  │ Shadow DOM 隔离          │  │   │
│  └────────┬──────────┘    │  │  widget.js 加载          │  │   │
│           │               │  └───────────┬────────────┘  │   │
│           │    /api/v1/*  │              │ /api/v1/chat  │   │
│           │   JWT Token   │              │ Agent Token   │   │
└───────────┼───────────────┴──────────────┼───────────────┘
            │                              │
    ┌───────▼──────────────────────────────▼───────────────┐
    │                    Pin 后端 (FastAPI)                   │
    │                                                        │
    │  ┌──────────┐  ┌────────────┐  ┌──────────────────┐   │
    │  │ Auth 中间件│  │ API 路由    │  │ 静态文件 Serve    │   │
    │  │ JWT+归属  │  │ RESTful    │  │ widget.js/admin  │   │
    │  └──────────┘  └─────┬──────┘  └──────────────────┘   │
    │                      │                                  │
    │  ┌───────────────────┼───────────────────────────┐     │
    │  │             Service Layer                      │     │
    │  │  ┌──────┐ ┌──────┐ ┌────────┐ ┌───────────┐  │     │
    │  │  │KB Svc│ │Ag Svc│ │FileProc│ │ChatService│  │     │
    │  │  └──┬───┘ └──┬───┘ └───┬────┘ └─────┬─────┘  │     │
    │  │     │        │         │             │        │     │
    │  │  ┌──┴────────┴─────────┴─────────────┴──┐     │     │
    │  │  │         Abstraction Layer             │     │     │
    │  │  │  VectorStore │ LLMProvider │ Storage  │     │     │
    │  │  └──────┬───────┴──────┬──────┴────┬─────┘     │     │
    │  └─────────┼──────────────┼───────────┼───────────┘     │
    │            │              │           │                  │
    │  ┌─────────▼──┐  ┌───────▼──┐  ┌─────▼──────────────┐  │
    │  │ PostgreSQL  │  │ OpenAI/  │  │   Local Disk        │  │
    │  │ + pgvector  │  │ Ollama   │  │   (→ S3/OSS later) │  │
    │  └────────────┘  └──────────┘  └────────────────────┘  │
    └────────────────────────────────────────────────────────┘
```

---

## 4. 技术栈

| 层级 | 技术 | 用途 |
|------|------|------|
| 后端框架 | FastAPI | REST API + WebSocket/SSE |
| ORM | SQLAlchemy 2.0 (async) | 数据库操作 |
| 数据校验 | Pydantic v2 | API Schema / 请求校验 |
| 数据库 | PostgreSQL + pgvector | 业务数据 + 向量存储 |
| RAG 框架 | LangChain | 文档分块、检索链 |
| LLM 编排 | LangGraph（预留） | 后续复杂 Workflow 编排 |
| LLM Provider | OpenAI / Ollama（MVP） | 统一 Provider 接口 |
| 前端框架 | Vue 3 + TypeScript | 管理后台 + 嵌入浮窗 |
| UI 组件库 | Naive UI | UI 组件 |
| 构建工具 | Vite | 前端构建 |
| 嵌入 | Shadow DOM | 浮窗样式隔离 |
| 部署 | Docker | 单容器部署 |

---

## 5. 项目目录结构（Monorepo）

```
pin/
├── backend/
│   ├── app/
│   │   ├── api/                # API 路由层
│   │   │   ├── v1/
│   │   │   │   ├── auth.py         # 登录/认证接口
│   │   │   │   ├── knowledge_bases.py  # 知识库 CRUD
│   │   │   │   ├── agents.py       # Agent CRUD + 对话接口
│   │   │   │   ├── files.py        # 文件上传/进度查询
│   │   │   │   └── widget.py       # widget.js 生成接口
│   │   │   └── deps.py             # 依赖注入（鉴权、归属校验）
│   │   ├── services/           # 业务逻辑层
│   │   │   ├── kb_service.py       # 知识库服务
│   │   │   ├── agent_service.py    # Agent 服务
│   │   │   ├── file_processor.py   # 文件解析分块入库
│   │   │   ├── chat_service.py     # RAG 对话服务
│   │   │   └── embedding_service.py # 向量化服务
│   │   ├── models/             # SQLAlchemy 数据模型
│   │   │   ├── base.py
│   │   │   ├── knowledge_base.py
│   │   │   ├── agent.py
│   │   │   ├── document.py
│   │   │   └── chunk.py
│   │   ├── schemas/            # Pydantic API Schema
│   │   │   ├── kb.py
│   │   │   ├── agent.py
│   │   │   ├── file.py
│   │   │   └── chat.py
│   │   ├── core/               # 核心基础设施
│   │   │   ├── config.py           # 配置管理
│   │   │   ├── security.py         # JWT/密码
│   │   │   ├── database.py         # 数据库连接
│   │   │   └── exceptions.py       # 全局异常处理
│   │   ├── providers/          # 抽象接口 + 具体实现
│   │   │   ├── vector_store/
│   │   │   │   ├── base.py         # VectorStore 抽象接口
│   │   │   │   └── pgvector.py     # pgvector 实现
│   │   │   ├── llm/
│   │   │   │   ├── base.py         # LLMProvider 抽象接口
│   │   │   │   ├── openai.py       # OpenAI 实现
│   │   │   │   └── ollama.py       # Ollama 实现
│   │   │   └── storage/
│   │   │       ├── base.py         # StorageProvider 抽象接口
│   │   │       └── local.py        # 本地磁盘实现
│   │   └── skills/             # Skill 系统（后续）
│   │       ├── base.py             # Skill 抽象接口
│   │       ├── registry.py         # SkillRegistry（热插拔）
│   │       └── runner.py           # 沙箱执行器
│   ├── main.py                 # FastAPI 应用入口
│   ├── alembic/                # 数据库迁移
│   └── pyproject.toml
├── frontend/
│   ├── src/
│   │   ├── admin/              # 管理后台
│   │   │   ├── pages/
│   │   │   │   ├── Login.vue
│   │   │   │   ├── KnowledgeBases.vue
│   │   │   │   ├── KnowledgeBaseDetail.vue
│   │   │   │   ├── Agents.vue
│   │   │   │   └── AgentDetail.vue
│   │   │   ├── layouts/
│   │   │   └── router.ts
│   │   ├── widget/             # 嵌入式浮窗
│   │   │   ├── entry.ts            # 浮窗独立入口
│   │   │   ├── ChatWidget.vue      # 对话主组件
│   │   │   ├── MessageList.vue     # 消息列表
│   │   │   ├── InputArea.vue       # 输入区域
│   │   │   └── loader.ts           # widget.js loader
│   │   └── shared/             # 共享
│   │       ├── api/                # API 调用封装 + 类型定义
│   │       ├── types/              # TypeScript 类型
│   │       └── utils/              # 工具函数
│   ├── admin.html               # 管理后台入口
│   └── vite.config.ts           # 多入口构建
├── static/                     # 生产环境静态文件（Vue build 输出）
│   ├── widget.js               # 嵌入脚本
│   ├── pin-widget.js           # 浮窗 Vue App
│   ├── pin-widget.css          # 浮窗样式
│   └── admin/                  # 管理后台
├── skills/                     # Skill 存放目录（后续）
├── docs/
│   ├── architecture.md         # 本文档
│   └── roadmap.md              # 功能排期文档
└── docker-compose.yml          # PostgreSQL + Pin 一键部署
```

---

## 6. API 设计规范

### 风格

- RESTful 资源导向
- 资源 ID 统一使用 UUID7（不可枚举、时间排序友好）
- 鉴权：JWT（管理后台）+ Agent Token（浮窗）
- 所有接口强制鉴权 + 资源归属校验

### 安全层

```
请求 → CORS 检查 → JWT/Token 验证 → 资源归属校验 → 速率限制 → 业务逻辑
         ↓              ↓                ↓              ↓
    域名白名单      401 Unauthorized  404 Not Found  429 Too Many Requests
    (可选)                           (不暴露资源      (防暴力枚举)
                                      是否存在)
```

### API 路由概览

#### 认证

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| POST | `/api/v1/auth/login` | 管理员登录 | 无 |
| POST | `/api/v1/auth/refresh` | 刷新 Token | Refresh Token |

#### 知识库

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| GET | `/api/v1/knowledge-bases` | 知识库列表 | JWT |
| POST | `/api/v1/knowledge-bases` | 创建知识库 | JWT |
| GET | `/api/v1/knowledge-bases/{id}` | 知识库详情 | JWT + 归属 |
| PUT | `/api/v1/knowledge-bases/{id}` | 更新知识库 | JWT + 归属 |
| DELETE | `/api/v1/knowledge-bases/{id}` | 删除知识库 | JWT + 归属 |
| GET | `/api/v1/knowledge-bases/{id}/documents` | 文件列表 | JWT + 归属 |
| POST | `/api/v1/knowledge-bases/{id}/documents` | 上传文件 | JWT + 归属 |
| GET | `/api/v1/knowledge-bases/{id}/documents/{doc_id}/status` | 文件处理进度 | JWT + 归属 |
| DELETE | `/api/v1/knowledge-bases/{id}/documents/{doc_id}` | 删除文件 | JWT + 归属 |

#### Agent

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| GET | `/api/v1/agents` | Agent 列表 | JWT |
| POST | `/api/v1/agents` | 创建 Agent | JWT |
| GET | `/api/v1/agents/{id}` | Agent 详情 | JWT + 归属 |
| PUT | `/api/v1/agents/{id}` | 更新 Agent（含挂载知识库） | JWT + 归属 |
| DELETE | `/api/v1/agents/{id}` | 删除 Agent | JWT + 归属 |
| POST | `/api/v1/agents/{id}/chat` | 对话接口（浮窗调用） | Agent Token |
| POST | `/api/v1/agents/{id}/chat/stream` | 流式对话（SSE） | Agent Token |

#### 浮窗嵌入

| 方法 | 路径 | 说明 | 鉴权 |
|------|------|------|------|
| GET | `/widget.js` | 返回嵌入脚本 | 无（公网） |

---

## 7. 核心模块设计

### 7.1 知识库模块 (KnowledgeBaseService)

```
文件上传 → 落盘 → 后台任务处理链路：
  ┌─────────────────────────────────────────────┐
  │ 1. 文件解析（根据格式选解析器）                │
  │    .txt/.md → 直接读取                        │
  │    .pdf     → PyMuPDF / pdfplumber           │
  │    .docx    → python-docx                    │
  │    .pptx    → python-pptx                    │
  │    .csv     → csv / pandas                   │
  ├─────────────────────────────────────────────┤
  │ 2. 文本分块                                  │
  │    RecursiveCharacterTextSplitter           │
  │    chunk_size / overlap 可配                 │
  │    保留元数据（文件名、页码、段落序号）          │
  ├─────────────────────────────────────────────┤
  │ 3. 向量化                                    │
  │    EmbeddingService → OpenAI/Ollama API      │
  ├─────────────────────────────────────────────┤
  │ 4. 入库                                      │
  │    PgVectorStore.add_documents()            │
  └─────────────────────────────────────────────┘

处理进度通过 GET /documents/{id}/status 轮询：
  pending → parsing → chunking → embedding → done / failed
```

### 7.2 Agent 模块 (AgentService)

```python
class AgentConfig:
    name: str
    description: str
    knowledge_bases: list[UUID]      # 挂载的知识库
    llm_provider: str                # "openai" | "ollama"
    llm_model: str                   # "gpt-4o" | "llama3" 等
    system_prompt: str               # 自定义系统提示词
    response_mode: str               # "stream" | "batch"
    token: str                       # Agent Token（自动生成，用于浮窗鉴权）
    allowed_domains: list[str] | None # 域名白名单（可选）
    temperature: float
    max_tokens: int
    top_k: int                       # RAG 检索返回数量
```

### 7.3 对话模块 (ChatService)

```
浮窗请求
  ↓
验证 Agent Token + 域名白名单
  ↓
多轮对话：从 localStorage session_id 恢复上下文
  ↓
RAG 检索：
  for each 挂载的知识库:
    VectorStore.similarity_search(query, top_k)
  合并结果，重排序
  ↓
Prompt 组装：
  System: {system_prompt}
  Context: {检索到的文档片段 + 来源标注}
  History: {本轮对话历史}
  User: {用户问题}
  ↓
LLM 调用：
  if stream → SSE StreamingResponse
  if batch → 一次性返回 JSON
  ↓
返回 {reply, sources[{file_name, chunk_text, score}], session_id}
```

### 7.4 浮窗模块

#### 嵌入方式

```html
<!-- 用户只需粘贴一行 -->
<script src="http://pin-server:8000/widget.js" data-agent-id="agent_abc123"></script>
```

#### 加载流程

```
浏览器解析 HTML
  ↓
下载 widget.js（~2KB loader）
  ↓
创建 Shadow DOM（样式隔离）
  ↓
动态加载 pin-widget.css + pin-widget.js（Vue3 + NaiveUI 打包，~80KB）
  ↓
初始化 Vue App → mount 到 Shadow DOM
  ↓
显示浮窗按钮 → 点击打开对话面板
```

#### 关键实现

| 技术点 | 方案 |
|--------|------|
| 样式隔离 | Shadow DOM `mode: 'closed'` |
| 状态管理 | Vue ref/reactive，无需 Pinia |
| 会话保持 | session_id 存 localStorage，关闭浮窗清除 |
| 流式渲染 | EventSource SSE → 逐字更新 Vue ref |
| Token 传递 | `<script data-agent-token="xxx">` 或 widget 内置配置 |

---

## 8. 阶段性演进路径

### MVP v0.1（当前）

```
管理后台：登录、知识库 CRUD、Agent CRUD、文件上传管理
浮窗对话：多轮对话（会话内）、SSE 流式 + 一次性
后端核心：RESTful API、JWT、RAG A+ 策略、pgvector
部署：Docker Compose（PostgreSQL + Pin）
```

### 后续迭代

| 版本 | 新增功能 |
|------|---------|
| v0.2 | 对话增强：多会话持久化、对话历史管理 |
| v0.3 | 知识库增强：结构化感知解析（B 策略）、批量上传 |
| v0.4 | 存储扩展：S3/MinIO/OSS 远程存储 |
| v0.5 | 多租户：子账号体系、知识库权限管理 |
| v0.6 | Skill 系统：热插拔 + 沙箱、Skill 市场 |
| v0.7 | MCP 协议：远程 Skill 接入 |
| v0.8 | Workflow：LangGraph 编排、外部 API 触发 |
| v1.0 | 企业级：LDAP/OIDC、审计日志、高可用 |

---

## 9. MVP 关键约束

| 约束 | 说明 |
|------|------|
| 单管理员 | 部署时初始化一个管理员账号，无多用户 |
| 无 Skill | 架构留接口，MVP 不实现 |
| 无 MCP | 架构留扩展点，后续接入 |
| 无 Workflow | LangGraph 预留，MVP 用 LangChain 简单 Chain |
| 本地存储 | 文件存本地磁盘，后续加 OSS Provider |
| 单会话记忆 | 关闭浮窗 = 新会话，不做多会话管理 |
| BackgroundTasks | 文件异步处理，进程重启任务丢失可接受 |

---

## 10. 开发 / 部署模式

### 开发模式

```
终端 1: cd backend && uvicorn main:app --reload --port 8000
终端 2: cd frontend && npm run dev  (Vite :5173, proxy /api → :8000)
浏览器: http://localhost:5173
```

### 生产部署

```
cd frontend && npm run build       → 输出到 static/
docker build -t pin:latest .
docker-compose up -d               → PostgreSQL + Pin 一键启动
浏览器: http://server:8000         → 管理后台 + API + 浮窗 JS 全部就绪
```

---

> 本文档与 `roadmap.md` 配套使用，后者定义了具体的开发优先级和阶段目标。
