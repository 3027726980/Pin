-- ============================================================
-- 迁移 002：Phase 3 文档处理 — 解析 / 分块 / 向量化 / 模型配置
-- ============================================================
-- 版本  : v0.4
-- 日期  : 2026-08-07
-- 依赖  : 迁移 001（is_chunked/is_vectorized 字段）、002（file_type）
-- 前置  : PostgreSQL 已启用 pgvector 扩展（CREATE EXTENSION vector）
-- ============================================================
-- 概述
--   本次迁移为 Phase 3 文档处理链路建立数据基础。
--
--   处理链路：
--     上传文件 → 解析（documents.content）→ 分块（chunks）→ 向量化（embeddings）
--
--   配置体系（三层）：
--     model_providers（厂商，seed 自 config.yaml）
--       └─ default_model_config（厂商默认模型参数，seed 自 config.yaml）
--            └─ user_model_config（用户创建，关联默认模型，可覆盖 base_url）
--
--   改动清单：
--     0. documents 新增 content + is_parsed
--     1. knowledge_bases 新增分块配置 + user_model_config_id
--     2. chunks     — 新建分块表
--     3. embeddings — 新建向量表（vector(4096) 零填充）
--     4. model_providers      — 新建厂商表
--     5. default_model_config — 新建默认模型表
--     6. user_model_config    — 新建用户配置表
--     7. 清理旧字段/表（embedding_model, embedding_dimension, model_config）
-- ============================================================
-- 回滚
--   ALTER TABLE documents DROP COLUMN content, DROP COLUMN is_parsed;
--   ALTER TABLE knowledge_bases DROP COLUMN chunk_size, chunk_overlap, chunk_separators, embedding_model, embedding_dimension;
--   DROP TABLE IF EXISTS embeddings, chunks, user_model_config, default_model_config, model_providers;
-- ============================================================


-- ════════════════════════════════════════════════════════════
-- 0. documents 新增字段
-- ════════════════════════════════════════════════════════════
-- content   : 解析后的完整纯文本（PDF → PyMuPDF, Office → markitdown）
--             修改分块配置后直接用此字段重新分块，无需重新解析原文件
-- is_parsed : 解析状态追踪（-1=失败, 0=未完成, 1=已完成, 2=进行中）
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_parsed
    SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN documents.content   IS '解析后的完整纯文本（PDF→PyMuPDF, Office→markitdown）';
COMMENT ON COLUMN documents.is_parsed IS '解析状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';


-- ════════════════════════════════════════════════════════════
-- 1. knowledge_bases 新增分块配置字段
-- ════════════════════════════════════════════════════════════
-- 不同知识库可独立配置分块参数，修改后需重新分块+向量化生效
--
-- chunk_separators : 递归分隔符（逗号分隔），读取时 split(",") 还原为列表
--                    优先级从高到低：## 标题 → 段落 → 句子 → 空格
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS chunk_size
    INT NOT NULL DEFAULT 800;
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS chunk_overlap
    INT NOT NULL DEFAULT 150;
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS chunk_separators
    VARCHAR(300) NOT NULL DEFAULT E'\n##,\n###,\n,。,., ';

COMMENT ON COLUMN knowledge_bases.chunk_size          IS '分块大小（字符数），默认 800。控制 RecursiveCharacterTextSplitter';
COMMENT ON COLUMN knowledge_bases.chunk_overlap       IS '相邻块重叠字符数，默认 150。防止文本在边界处被截断';
COMMENT ON COLUMN knowledge_bases.chunk_separators    IS '递归分隔符（逗号分隔），优先级从高到低：标题→段落→句子→空格';


-- ════════════════════════════════════════════════════════════
-- 2. chunks — 分块表
-- ════════════════════════════════════════════════════════════
-- 每个文档被 RecursiveCharacterTextSplitter 切分为多个块
-- chunk_index 同文档内从 0 递增，metadata 为 JSONB 可存标题/页码等
-- 关系：documents 1:N chunks → embeddings 1:1 chunks
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID          NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kb_id           UUID          NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    chunk_index     INT           NOT NULL DEFAULT 0,
    content         TEXT          NOT NULL,
    metadata        JSONB,
    status          SMALLINT      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_kb_id  ON chunks(kb_id);
CREATE INDEX IF NOT EXISTS idx_chunks_status ON chunks(status);

COMMENT ON TABLE chunks                IS '分块表：文档被 RecursiveCharacterTextSplitter 递归分块后的文本片段';
COMMENT ON COLUMN chunks.document_id   IS '所属文档 ID（documents 1:N chunks）';
COMMENT ON COLUMN chunks.kb_id         IS '所属知识库 ID（冗余存储，加速按知识库检索过滤）';
COMMENT ON COLUMN chunks.chunk_index   IS '块序号，同文档内从 0 递增，保持原文顺序';
COMMENT ON COLUMN chunks.content       IS '分块后的文本内容';
COMMENT ON COLUMN chunks.metadata      IS '元信息 JSONB：可存标题/页码/来源段落（预留 Phase 4 RAG 检索高亮）';
COMMENT ON COLUMN chunks.status        IS '-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON INDEX idx_chunks_doc_id     IS '按文档查询索引：列出某文档的所有块';
COMMENT ON INDEX idx_chunks_kb_id      IS '按知识库查询索引：跨文档检索过滤';
COMMENT ON INDEX idx_chunks_status     IS '按状态过滤索引：查询处理进度';


-- ════════════════════════════════════════════════════════════
-- 3. embeddings — 向量表
-- ════════════════════════════════════════════════════════════
-- 每个 chunk 对应一条 embedding，chunk_id UNIQUE 确保一对一
-- vector(4096) 为统一最大维度，小维度模型零填充（余弦相似度不变）
-- 零填充原理：小维度后面补 0，点积和范数不受影响
-- 用途：Phase 4 RAG 检索时 pgvector <=> 余弦距离取 Top-K
CREATE TABLE IF NOT EXISTS embeddings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id        UUID          NOT NULL UNIQUE REFERENCES chunks(id) ON DELETE CASCADE,
    kb_id           UUID          NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    embedding       vector(4096),
    status          SMALLINT      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id ON embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_kb_id    ON embeddings(kb_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_status   ON embeddings(status);

COMMENT ON TABLE embeddings                IS '向量表：分块的 Embedding 向量，vector(4096) 统一维度，小维度零填充';
COMMENT ON COLUMN embeddings.chunk_id      IS '关联的分块 ID（chunks 1:1 embeddings），UNIQUE 约束';
COMMENT ON COLUMN embeddings.kb_id         IS '所属知识库 ID（冗余，加速按知识库检索过滤）';
COMMENT ON COLUMN embeddings.embedding     IS '向量数据，固定 4096 维。1536 维模型后补 488 个 0，余弦相似度不变';
COMMENT ON COLUMN embeddings.status        IS '-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON INDEX idx_embeddings_chunk_id   IS '按分块查询索引：一个 chunk 查它的向量';
COMMENT ON INDEX idx_embeddings_kb_id      IS '按知识库查询索引：跨文档向量检索';
COMMENT ON INDEX idx_embeddings_status     IS '按状态过滤索引：查询向量化进度';


-- ════════════════════════════════════════════════════════════
-- 4. model_providers — 模型厂商表
-- ════════════════════════════════════════════════════════════
-- 启动时从 config.yaml model_providers 段自动创建，用户只读
-- 厂商名唯一，如 aliyun / openai
-- 关系：model_providers 1:N default_model_config
CREATE TABLE IF NOT EXISTS model_providers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(50)   NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE model_providers      IS '模型厂商表：启动时从 config.yaml 自动创建，用户只读，不可增删';
COMMENT ON COLUMN model_providers.name IS '厂商名（unique）：aliyun / openai / ollama';


-- ════════════════════════════════════════════════════════════
-- 5. default_model_config — 默认模型配置表
-- ════════════════════════════════════════════════════════════
-- 启动时从 config.yaml model_providers.{provider}.models 自动创建，用户只读
-- 每个厂商下可有多个模型（如 text-embedding-v1 / v2 / v3）
-- 存储各模型的默认参数：base_url、dimension、model_type
-- 关系：model_providers 1:N default_model_config → user_model_config 以此为基础
CREATE TABLE IF NOT EXISTS default_model_config (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    provider        VARCHAR(50)   NOT NULL,
    model_name      VARCHAR(200)  NOT NULL,
    model_type      SMALLINT      NOT NULL,
    base_url        VARCHAR(500)  NOT NULL,
    dimension       INT,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE default_model_config                IS '默认模型配置表：启动时从 config.yaml 自动创建，用户只读';
COMMENT ON COLUMN default_model_config.provider      IS '所属厂商名，对应 model_providers.name';
COMMENT ON COLUMN default_model_config.model_name    IS '模型名：text-embedding-v1 / gpt-4o 等';
COMMENT ON COLUMN default_model_config.model_type    IS '1=embedding, 2=LLM（3~9 预留：图片/语音/视频）';
COMMENT ON COLUMN default_model_config.base_url      IS 'API 地址（厂商默认，用户创建配置时可覆盖）';
COMMENT ON COLUMN default_model_config.dimension     IS 'embedding 输出维度，LLM 时 NULL';


-- ════════════════════════════════════════════════════════════
-- 6. user_model_config — 用户模型配置表
-- ════════════════════════════════════════════════════════════
-- 用户在前端创建，选模型后自动带入 default_model_config 的参数
-- base_url 可手动覆盖（自建代理/私有化部署等场景）
-- api_key 由用户填写
-- 向量化时 find_active_embedding() 查此表取 active 的那条配置
CREATE TABLE IF NOT EXISTS user_model_config (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        VARCHAR(50)   NOT NULL,
    model_name      VARCHAR(200)  NOT NULL,
    model_type      SMALLINT      NOT NULL,
    base_url        VARCHAR(500),
    api_key         VARCHAR(500),
    dimension       INT,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_umc_user_id ON user_model_config(user_id);
CREATE INDEX IF NOT EXISTS idx_umc_type    ON user_model_config(model_type);

COMMENT ON TABLE user_model_config               IS '用户模型配置表：用户在前端创建，base_url=NULL 时用 default_model_config 的值';
COMMENT ON COLUMN user_model_config.user_id      IS '所属用户 ID（多租户预留）';
COMMENT ON COLUMN user_model_config.provider     IS '厂商名，用于 EmbeddingService switch 分发';
COMMENT ON COLUMN user_model_config.model_name   IS '模型名，传给 SDK/API';
COMMENT ON COLUMN user_model_config.model_type   IS '1=embedding, 2=LLM';
COMMENT ON COLUMN user_model_config.base_url     IS 'API 地址。用户可覆盖（自建代理/私有化部署），NULL 则用 default 的';
COMMENT ON COLUMN user_model_config.api_key      IS '用户填的 API Key（阿里云 DashScope / OpenAI 等）';
COMMENT ON COLUMN user_model_config.dimension    IS '向量维度（embedding 用，LLM 为 NULL）';
COMMENT ON COLUMN user_model_config.is_active    IS '是否启用。向量化时只取 active 且 model_type=1 的';
COMMENT ON INDEX idx_umc_user_id                IS '按用户查询索引：列出某用户的所有配置';
COMMENT ON INDEX idx_umc_type                   IS '按类型查询索引：快速找 embedding 或 LLM 配置';


-- ════════════════════════════════════════════════════════════
-- 7. 清理废弃的 model_config 表
-- ════════════════════════════════════════════════════════════
-- 旧版单体 model_config 表已被 model_providers + default_model_config + user_model_config 取代
DROP TABLE IF EXISTS model_config;

-- ═══ 8. knowledge_bases 新增 user_model_config_id ═══
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS user_model_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL;

COMMENT ON COLUMN knowledge_bases.user_model_config_id IS '关联的用户模型配置，有 API Key 时使用';
