# Pin 项目功能排期文档

> **产品名**: Pin  
> **当前版本**: MVP v0.1  
> **配套文档**: `architecture.md`

---

## MVP v0.1 功能清单

### 开发阶段总览

```
Phase 1: 后端基础设施
Phase 2: 知识库管理
Phase 3: Agent 管理 + 对话引擎
Phase 4: 管理后台前端
Phase 5: 浮窗嵌入
Phase 6: 联调 + 部署
```

---

## Phase 1: 后端基础设施

> **目标**: 搭建可运行的后端骨架，所有后续功能的基础

| 编号 | 功能 | 优先级 | 详细说明 |
|------|------|--------|---------|
| P1-1 | 项目结构初始化 | P0 | FastAPI 项目骨架、配置管理（`config.py`）、日志系统 |
| P1-2 | 数据库模型 | P0 | SQLAlchemy 2.0 async + pgvector，定义所有 MVP 表的 Model |
| P1-3 | 数据库迁移 | P0 | Alembic 配置，自动生成迁移脚本 |
| P1-4 | Pydantic Schema | P0 | 定义请求/响应的 Schema 层，与 Model 分离 |
| P1-5 | JWT 鉴权 | P0 | 管理员登录/Token 签发/刷新、`get_current_user` 依赖注入 |
| P1-6 | 全局异常处理 | P1 | 统一异常格式、HTTP 异常映射、404/401/422 标准化 |
| P1-7 | CORS + 安全中间件 | P1 | CORS 配置、速率限制（SlowAPI）、UUID 不可枚举 |
| P1-8 | Docker Compose | P1 | PostgreSQL + pgvector + Pin 的单文件部署配置 |

### Phase 1 交付标准

```
✅ 后端能启动，数据库表自动创建
✅ POST /api/v1/auth/login 返回 JWT Token
✅ 未登录请求返回 401
✅ API 文档可通过 /docs 访问（Swagger）
```

---

## Phase 2: 知识库管理

> **目标**: 完整的知识库 CRUD + 文件上传 + 解析入库流程

| 编号 | 功能 | 优先级 | 详细说明 |
|------|------|--------|---------|
| P2-1 | 知识库 CRUD API | P0 | 创建/列表/详情/更新/删除，归属校验 |
| P2-2 | 文件上传接口 | P0 | 单文件上传、格式校验（.txt/.md/.pdf/.docx/.pptx/.csv） |
| P2-3 | 文件解析器 | P0 | 按格式路由解析器，提取纯文本 |
| P2-4 | 文本分块 | P0 | `RecursiveCharacterTextSplitter`，chunk_size/overlap 可配置 |
| P2-5 | Embedding 服务 | P0 | 统一 Provider 接口 + OpenAI 实现 + Ollama 实现 |
| P2-6 | PgVectorStore | P0 | VectorStore 抽象接口 + pgvector 实现（add/search/delete_by_kb） |
| P2-7 | 文件处理任务 | P0 | FastAPI BackgroundTasks 异步处理，处理状态追踪 |
| P2-8 | 处理进度查询 | P1 | GET /documents/{id}/status 返回进度（pending/parsing/chunking/embedding/done/failed） |
| P2-9 | 文件列表 + 删除 | P1 | 知识库下的文件列表、单文件删除（同时删向量数据） |

### Phase 2 交付标准

```
✅ 创建知识库 → 上传 PDF → 后台自动解析入库
✅ 轮询状态接口能追踪处理进度
✅ 删除文件 → 对应向量数据同步删除
✅ OpenAI 和 Ollama 均可配置为 Embedding Provider
```

---

## Phase 3: Agent 管理 + 对话引擎

> **目标**: Agent CRUD + 浮窗对话接口（RAG 问答）

| 编号 | 功能 | 优先级 | 详细说明 |
|------|------|--------|---------|
| P3-1 | Agent CRUD API | P0 | 创建/列表/详情/更新/删除，挂载知识库配置 |
| P3-2 | Agent Token 生成 | P0 | 创建 Agent 时自动生成唯一 Token，用于浮窗鉴权 |
| P3-3 | 域名白名单校验 | P1 | 创建 Agent 时可选配置，对话接口校验 Origin/Referer |
| P3-4 | 对话接口（一次性） | P0 | POST /agents/{id}/chat，完整 RAG 链路：检索→组装→LLM→返回 |
| P3-5 | 对话接口（SSE 流式） | P0 | POST /agents/{id}/chat/stream，SSE 逐字推送 |
| P3-6 | 多轮对话上下文 | P0 | session_id 机制，同一会话内保持对话历史 |
| P3-7 | 来源引用 | P1 | 回答附带检索到的文档片段和文件名，前端可渲染 |
| P3-8 | LLM Provider 实现 | P0 | OpenAI 实现 + Ollama 实现，统一接口，Agent 可切换 |

### Phase 3 交付标准

```
✅ 创建 Agent → 挂载知识库 → 配置模型参数
✅ curl POST /agents/{id}/chat → 返回带来源引用的 RAG 回答
✅ SSE 流式接口逐字推送
✅ 同一 session_id 内多轮对话保持上下文
✅ 无 session_id 或关闭浮窗 → 新会话
```

---

## Phase 4: 管理后台前端

> **目标**: Vue3 + Naive UI 管理后台，管理员可视化操作

| 编号 | 功能 | 优先级 | 详细说明 |
|------|------|--------|---------|
| P4-1 | 项目脚手架 | P0 | Vue3 + TS + Vite + NaiveUI + Vue Router |
| P4-2 | 登录页面 | P0 | 用户名密码登录、Token 持久化、401 自动跳登录 |
| P4-3 | 布局框架 | P0 | 侧边导航 + 顶栏 + 内容区 |
| P4-4 | 知识库列表页 | P0 | 表格/卡片视图、搜索、创建/删除 |
| P4-5 | 知识库详情页 | P0 | 基本信息编辑 + 文件上传（拖拽）+ 文件列表 + 处理状态 |
| P4-6 | Agent 列表页 | P0 | Agent 列表、创建/删除 |
| P4-7 | Agent 详情页 | P0 | Agent 配置表单：名称/模型/知识库多选/prompt/响应模式/域名白名单 |
| P4-8 | 嵌入代码生成 | P1 | Agent 详情页显示嵌入代码，一键复制 |
| P4-9 | API 调用封装 | P0 | 统一 fetch 封装、类型定义、错误处理、Token 自动附加 |

### Phase 4 交付标准

```
✅ 登录 → 知识库列表 → 创建知识库 → 上传文件 → 看到处理完成
✅ 创建 Agent → 配置挂载知识库 → 保存
✅ Agent 详情页复制嵌入代码 → 可在测试页面验证
```

---

## Phase 5: 浮窗嵌入组件

> **目标**: 零代码嵌入的浮窗聊天组件

| 编号 | 功能 | 优先级 | 详细说明 |
|------|------|--------|---------|
| P5-1 | widget.js Loader | P0 | 纯 JS ~2KB，读取 data-* 属性，创建 Shadow DOM，动态加载组件 |
| P5-2 | Vue3 浮窗应用 | P0 | ChatWidget 主组件、消息列表、输入区域、发送按钮 |
| P5-3 | NaiveUI 组件集成 | P0 | NInput/NButton/NCard/NScrollbar/NPopover 按需引入 |
| P5-4 | 对话 UI | P0 | 消息气泡（用户/AI）、Markdown 渲染、代码高亮、来源引用展示 |
| P5-5 | SSE 流式渲染 | P0 | EventSource 接收 SSE 事件，逐字更新消息气泡 |
| P5-6 | 浮窗动画 | P1 | 按钮弹出/收起动画、打字机效果、loading 状态 |
| P5-7 | 会话管理 | P0 | localStorage 存 session_id，关闭浮窗清除 |
| P5-8 | 样式隔离 | P0 | Shadow DOM 封装，不污染宿主页面，不被宿主污染 |
| P5-9 | 响应式适配 | P1 | 移动端/桌面端自适应，浮窗尺寸可配 |
| P5-10 | Vite 多入口构建 | P0 | admin + widget 同时打包，输出到 static/ |
| P5-11 | FastAPI 静态文件 Serve | P0 | `/widget.js` 路由 + 统一 Serve static/ |

### Phase 5 交付标准

```
✅ 在任意 HTML 页面贴 <script> → 右下角出现浮窗
✅ 点击浮窗 → 展开对话面板
✅ 输入问题 → 流式逐字返回答案 + 来源引用
✅ 关闭浮窗 → 重新打开 → 新会话
✅ 宿主页面样式不影响浮窗外观
```

---

## Phase 6: 联调 + 部署

> **目标**: 全链路打通，可部署运行

| 编号 | 功能 | 优先级 | 详细说明 |
|------|------|--------|---------|
| P6-1 | 全链路联调 | P0 | 管理后台创建知识库→上传文件→创建Agent→浮窗对话，全流程验证 |
| P6-2 | Docker 镜像构建 | P0 | 多阶段 Dockerfile（前端 build + 后端打包） |
| P6-3 | Docker Compose | P0 | PostgreSQL + Pin 一键启动脚本 |
| P6-4 | 环境变量配置 | P0 | 数据库连接、LLM API Key、管理员初始密码等通过环境变量注入 |
| P6-5 | 健康检查 | P1 | API 健康检查端点，Docker healthcheck |
| P6-6 | 部署文档 | P1 | README 含快速开始、配置说明、Docker 部署步骤 |

### Phase 6 交付标准

```
✅ docker-compose up -d → 浏览器打开 → 登录管理后台
✅ 全流程：创建知识库→上传文件→创建Agent→嵌入浮窗→对话
✅ 浮窗在任意页面正常工作
```

---

## 功能优先级说明

| 级别 | 含义 |
|------|------|
| P0 | 核心功能，必须完成才能交付 MVP |
| P1 | 重要功能，提升可用性，MVP 内完成 |
| P2 | 锦上添花，允许延后 |

---

## MVP 排期建议（单人开发）

| 阶段 | 预估工期 | 累计 |
|------|---------|------|
| Phase 1: 后端基础设施 | 3-5 天 | 第 1 周 |
| Phase 2: 知识库管理 | 5-7 天 | 第 2 周 |
| Phase 3: Agent + 对话引擎 | 5-7 天 | 第 3 周 |
| Phase 4: 管理后台前端 | 5-7 天 | 第 4 周 |
| Phase 5: 浮窗嵌入组件 | 5-7 天 | 第 5 周 |
| Phase 6: 联调 + 部署 | 2-3 天 | 第 6 周 |
| **合计** | **25-36 天** | **约 6 周** |

---

## 后续版本规划

### v0.2 - 对话增强

| 功能 | 说明 |
|------|------|
| 多会话持久化 | 访客可查看历史对话、继续之前的对话 |
| Agent 配置项 | 单会话记忆 / 多会话持久化 开关 |
| 对话管理 | 管理员可查看/删除访客对话记录 |

### v0.3 - 知识库增强

| 功能 | 说明 |
|------|------|
| 结构化感知解析 | PDF 表格保留、Markdown 章节层级 |
| 批量上传 | 一次上传多个文件、文件夹拖拽上传 |
| 知识库设置 | 独立配置 chunk_size、overlap、检索 top_k |

### v0.4 - 存储扩展

| 功能 | 说明 |
|------|------|
| S3/MinIO Provider | 实现 StorageProvider 接口 |
| OSS Provider | 阿里云/腾讯云等国内对象存储 |
| 存储切换 | 配置项切换存储后端 |

### v0.5 - 多租户

| 功能 | 说明 |
|------|------|
| 子账号体系 | 管理员创建用户、分配角色 |
| 知识库权限 | 私有/共享/只读权限控制 |
| 用户自主管理 | 用户创建自己的知识库和 Agent |

### v0.6 - Skill 系统

| 功能 | 说明 |
|------|------|
| Skill 接口 | 标准化 Skill 协议（name/description/parameters/execute） |
| 热插拔 | 文件系统监听 + 前端上传，运行时加载卸载 |
| 沙箱执行 | subprocess 隔离 + 资源限制 |
| Agent 挂载 | Agent 配置中勾选启用的 Skill |

### v0.7 - MCP 协议

| 功能 | 说明 |
|------|------|
| MCP Client | Pin 作为 MCP 客户端接入远程 Skill Server |
| MCP 适配器 | MCP Skill 包装为 Pin Skill 接口 |
| 工具市场 | 社区 Skill 发现和安装 |

### v0.8 - Workflow 编排

| 功能 | 说明 |
|------|------|
| LangGraph 集成 | 替代基础 Chain，支持复杂工作流 |
| 可视化编排 | 拖拽式 Workflow 设计器 |
| 外部 API 触发 | 外部系统通过 API 触发 Workflow 执行 |
| Webhook 回调 | Workflow 完成后回调通知 |

### v1.0 - 企业级

| 功能 | 说明 |
|------|------|
| 企业 SSO | LDAP / OIDC / SAML 集成 |
| 审计日志 | 全操作记录，合规审计 |
| 高可用部署 | 多实例 + 负载均衡 |
| 监控告警 | Prometheus + Grafana |

---

## 技术债 & 待定事项

| 事项 | 说明 | 决策节点 |
|------|------|---------|
| UUID7 vs UUID4 | UUID7（时间排序）对索引更友好，但需额外依赖 `uuid6` | Phase 1 前决定 |
| LangGraph 引入时机 | 目前 MVP 用 LangChain Chain，何时升级 | v0.3 后评估 |
| Skill 安全级别 | MVP 后需要评估是否需要 Docker 沙箱 | v0.6 开发前 |
| 文件处理队列 | BackgroundTasks 升级到 ARQ/Celery 的时机 | 遇到批量上传需求时 |
| 管理后台 SSR/SEO | 管理后台是 SPA，是否需要 SSR | 用户反馈决定 |

---

> 本文档为活文档，随开发推进持续更新。开发时请以 Phase 为单位推进，每完成一个 Phase 进行阶段性验证。
