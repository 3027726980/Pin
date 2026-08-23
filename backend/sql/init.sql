-- ============================================================
-- Pin 数据库初始化脚本
-- 数据库: PostgreSQL 17 + pgvector
-- 版本  : v0.7 (Phase 4.8)
-- 说明  : 本文件为最终结构（含全部增量迁移 001~017 的累积结果）
-- ============================================================

-- 1. 扩展
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";  -- UUID v4 生成函数
CREATE EXTENSION IF NOT EXISTS "vector";      -- 向量数据类型 + 相似度检索（Phase 3+ 启用）

-- ============================================================
-- 2. 用户表
--     MVP 阶段仅一个管理员账号，后续扩展为多租户用户体系
-- ============================================================
CREATE TABLE IF NOT EXISTS users (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    username        VARCHAR(100)  NOT NULL UNIQUE,
    hashed_password VARCHAR(255)  NOT NULL,
    is_superuser    BOOLEAN       NOT NULL DEFAULT FALSE,
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

-- 索引
CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
COMMENT ON INDEX idx_users_username IS '用户名查询索引，登录时按 username 查用户';

-- 表 + 字段注释
COMMENT ON TABLE users IS '用户表：MVP 阶段仅存一个管理员，v0.5 扩展为多租户用户体系';
COMMENT ON COLUMN users.id IS '主键，UUID v4';
COMMENT ON COLUMN users.username IS '登录用户名，唯一';
COMMENT ON COLUMN users.hashed_password IS 'bcrypt 哈希密文，不可逆';
COMMENT ON COLUMN users.is_superuser IS '管理员标识：true=超级管理员，false=普通用户';
COMMENT ON COLUMN users.is_active IS '账号启用状态：true=正常，false=禁用';
COMMENT ON COLUMN users.created_at IS '记录创建时间';
COMMENT ON COLUMN users.updated_at IS '记录最后更新时间';

-- ============================================================
-- 3. Access Token 白名单
--     仅此表中的 Access Token 有效
--     刷新/登出时删除旧记录 → 旧 Token 即时失效
-- ============================================================
CREATE TABLE IF NOT EXISTS access_token_whitelist (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_jti   VARCHAR(36) NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_access_whitelist_jti
    ON access_token_whitelist(token_jti);
CREATE INDEX IF NOT EXISTS idx_access_whitelist_user
    ON access_token_whitelist(user_id);

COMMENT ON TABLE access_token_whitelist IS 'Access Token 白名单：只存当前有效的 Access Token';
COMMENT ON COLUMN access_token_whitelist.id IS '主键，UUID v4';
COMMENT ON COLUMN access_token_whitelist.user_id IS '所属用户 ID';
COMMENT ON COLUMN access_token_whitelist.token_jti IS 'JWT ID，与 Token payload 中的 jti 一致';
COMMENT ON COLUMN access_token_whitelist.expires_at IS '过期时间，超时后即使未删除也视为无效';
COMMENT ON COLUMN access_token_whitelist.created_at IS '记录创建时间';
COMMENT ON INDEX idx_access_whitelist_jti IS '按 jti 查询索引，校验 Token 时使用';
COMMENT ON INDEX idx_access_whitelist_user IS '按用户查询索引，批量撤销用户 Token 时使用';

-- ============================================================
-- 4. Refresh Token 白名单
--     仅此表中的 Refresh Token 有效
--     刷新时删旧插新 → 实现 Token 轮转
-- ============================================================
CREATE TABLE IF NOT EXISTS refresh_token_whitelist (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id     UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    token_jti   VARCHAR(36) NOT NULL UNIQUE,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_refresh_whitelist_jti
    ON refresh_token_whitelist(token_jti);
CREATE INDEX IF NOT EXISTS idx_refresh_whitelist_user
    ON refresh_token_whitelist(user_id);

COMMENT ON TABLE refresh_token_whitelist IS 'Refresh Token 白名单：只存当前有效的 Refresh Token';
COMMENT ON COLUMN refresh_token_whitelist.id IS '主键，UUID v4';
COMMENT ON COLUMN refresh_token_whitelist.user_id IS '所属用户 ID';
COMMENT ON COLUMN refresh_token_whitelist.token_jti IS 'JWT ID，与 Token payload 中的 jti 一致';
COMMENT ON COLUMN refresh_token_whitelist.expires_at IS '过期时间，超时后即使未删除也视为无效';
COMMENT ON COLUMN refresh_token_whitelist.created_at IS '记录创建时间';
COMMENT ON INDEX idx_refresh_whitelist_jti IS '按 jti 查询索引，校验 Token 时使用';
COMMENT ON INDEX idx_refresh_whitelist_user IS '按用户查询索引，批量撤销用户 Token 时使用';

-- ============================================================
-- 5. 知识库表
--     Phase 2：基本信息 + 上传约束
--     Phase 3：分块配置 + 关联 user_model_config
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id               UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                  VARCHAR(200) NOT NULL,
    description           TEXT,
    allowed_extensions    VARCHAR(500),
    max_file_size         BIGINT      NOT NULL DEFAULT 104857600,
    allow_multiple        BOOLEAN     NOT NULL DEFAULT TRUE,
    chunk_size            INT         NOT NULL DEFAULT 800,
    chunk_overlap         INT         NOT NULL DEFAULT 150,
    chunk_separators      VARCHAR(300) NOT NULL DEFAULT E'\n##,\n###,\n,。,., ',
    embedding_model       VARCHAR(100) NOT NULL DEFAULT 'bge-small-zh-v1.5',
    embedding_dimension   INT         NOT NULL DEFAULT 4096,
    user_model_config_id  UUID,       -- 外键在 user_model_config 建表后补充（第 11 节末尾，避免前向引用）
    status                SMALLINT    NOT NULL DEFAULT 1,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_kb_user_id ON knowledge_bases(user_id);
CREATE INDEX IF NOT EXISTS idx_kb_status  ON knowledge_bases(status);

COMMENT ON TABLE knowledge_bases IS '知识库表：存储知识库配置和上传约束';
COMMENT ON COLUMN knowledge_bases.id IS '主键，UUID v4';
COMMENT ON COLUMN knowledge_bases.user_id IS '创建者用户 ID';
COMMENT ON COLUMN knowledge_bases.name IS '知识库名称';
COMMENT ON COLUMN knowledge_bases.description IS '描述';
COMMENT ON COLUMN knowledge_bases.allowed_extensions IS '允许的文件后缀，逗号分隔如 .pdf,.txt,.md；为空则允许所有类型';
COMMENT ON COLUMN knowledge_bases.max_file_size IS '单文件大小上限（字节），默认 104857600 = 100MB';
COMMENT ON COLUMN knowledge_bases.allow_multiple IS '是否允许多文件上传';
COMMENT ON COLUMN knowledge_bases.chunk_size IS '分块大小（字符数），默认 800';
COMMENT ON COLUMN knowledge_bases.chunk_overlap IS '相邻块重叠字符数，默认 150';
COMMENT ON COLUMN knowledge_bases.chunk_separators IS '递归分隔符（逗号分隔），优先级从高到低';
COMMENT ON COLUMN knowledge_bases.embedding_model IS '选用的 Embedding 模型，默认 bge-small-zh-v1.5（本地，零配置）';
COMMENT ON COLUMN knowledge_bases.embedding_dimension IS '模型输出向量维度，默认 4096（向下兼容，小维度零填充）';
COMMENT ON COLUMN knowledge_bases.user_model_config_id IS '关联的用户模型配置，有 API Key 时优先使用';
COMMENT ON COLUMN knowledge_bases.status IS '0=禁用, 1=启用, 9=逻辑删除';
COMMENT ON COLUMN knowledge_bases.created_at IS '记录创建时间';
COMMENT ON COLUMN knowledge_bases.updated_at IS '记录最后更新时间';
COMMENT ON INDEX idx_kb_user_id IS '按创建者查询索引，列出用户的知识库时使用';
COMMENT ON INDEX idx_kb_status IS '按状态过滤索引，查询时排除已删除记录';

-- ============================================================
-- 6. 文档表
--     Phase 2：文件元信息
--     Phase 3：content（解析文本）+ is_parsed/is_chunked/is_vectorized（状态追踪）
-- ============================================================
CREATE TABLE IF NOT EXISTS documents (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    knowledge_base_id   UUID        NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    filename            VARCHAR(500) NOT NULL,
    file_path           VARCHAR(1000) NOT NULL,
    file_size           BIGINT      NOT NULL,
    file_type           VARCHAR(100),               -- 文件后缀，如 .pdf，无后缀则为 NULL
    content             TEXT,
    status              SMALLINT    NOT NULL DEFAULT 1,
    is_parsed           SMALLINT    NOT NULL DEFAULT 0,
    is_chunked          SMALLINT    NOT NULL DEFAULT 0,
    is_vectorized       SMALLINT    NOT NULL DEFAULT 0,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_doc_kb_id  ON documents(knowledge_base_id);
CREATE INDEX IF NOT EXISTS idx_doc_status ON documents(status);

COMMENT ON TABLE documents IS '文档表：存储上传到知识库中的文件元信息';
COMMENT ON COLUMN documents.id IS '主键，UUID v4';
COMMENT ON COLUMN documents.knowledge_base_id IS '所属知识库 ID';
COMMENT ON COLUMN documents.user_id IS '上传者用户 ID';
COMMENT ON COLUMN documents.filename IS '原始文件名';
COMMENT ON COLUMN documents.file_path IS '相对路径，如 uploads/{kb_id}/{name}_{uuid}.{ext}';
COMMENT ON COLUMN documents.file_size IS '文件大小（字节）';
COMMENT ON COLUMN documents.file_type IS '文件后缀，如 .pdf，无后缀则为 NULL';
COMMENT ON COLUMN documents.content IS '解析后的完整纯文本';
COMMENT ON COLUMN documents.status IS '0=禁用, 1=启用, 9=逻辑删除';
COMMENT ON COLUMN documents.is_parsed IS '解析状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON COLUMN documents.is_chunked IS '切片状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON COLUMN documents.is_vectorized IS '向量化状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON COLUMN documents.created_at IS '记录创建时间';
COMMENT ON COLUMN documents.updated_at IS '记录最后更新时间';
COMMENT ON INDEX idx_doc_kb_id IS '按知识库查询索引，列出知识库下文件时使用';
COMMENT ON INDEX idx_doc_status IS '按状态过滤索引，查询时排除已删除记录';

-- ============================================================
-- 7. 分块表
--     Phase 3：存储文档分块后的文本片段
-- ============================================================
CREATE TABLE IF NOT EXISTS chunks (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    document_id     UUID          NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    kb_id           UUID          NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    chunk_index     INT           NOT NULL DEFAULT 0,
    content         TEXT          NOT NULL,
    metadata        JSONB,
    status          SMALLINT      NOT NULL DEFAULT 1,
    is_vectorized   SMALLINT      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id  ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_kb_id   ON chunks(kb_id);
CREATE INDEX IF NOT EXISTS idx_chunks_status  ON chunks(status);

COMMENT ON TABLE chunks IS '分块表：存储文档分块后的文本片段';
COMMENT ON COLUMN chunks.document_id IS '所属文档 ID';
COMMENT ON COLUMN chunks.kb_id IS '所属知识库 ID（冗余加速检索）';
COMMENT ON COLUMN chunks.chunk_index IS '块序号，同一文档内从 0 递增';
COMMENT ON COLUMN chunks.content IS '分块文本内容';
COMMENT ON COLUMN chunks.metadata IS '来源标题、页码等元信息';
COMMENT ON COLUMN chunks.status IS '0=禁用, 1=启用, 9=软删除';
COMMENT ON COLUMN chunks.is_vectorized IS '向量化状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON INDEX idx_chunks_doc_id IS '按文档查询索引';
COMMENT ON INDEX idx_chunks_kb_id IS '按知识库查询索引';
COMMENT ON INDEX idx_chunks_status IS '按状态过滤索引';

-- ============================================================
-- 8. 向量表
--     Phase 3：存储分块文本的 Embedding 向量，统一 vector(4096)
-- ============================================================
CREATE TABLE IF NOT EXISTS embeddings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id        UUID          NOT NULL UNIQUE REFERENCES chunks(id) ON DELETE CASCADE,
    kb_id           UUID          NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    embedding       vector(4096),
    status          SMALLINT      NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id ON embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_kb_id    ON embeddings(kb_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_status   ON embeddings(status);

COMMENT ON TABLE embeddings IS '向量表：存储分块文本的 Embedding 向量，整体 vector(4096)，小维度模型零填充';
COMMENT ON COLUMN embeddings.chunk_id IS '关联的分块 ID，一一对应';
COMMENT ON COLUMN embeddings.kb_id IS '所属知识库 ID（冗余加速检索）';
COMMENT ON COLUMN embeddings.embedding IS '向量数据，固定 4096 维（小维度零填充）';
COMMENT ON COLUMN embeddings.status IS '0=禁用, 1=启用, 9=软删除（与关联 chunk 状态同步）';
COMMENT ON INDEX idx_embeddings_chunk_id IS '按分块查询索引';
COMMENT ON INDEX idx_embeddings_kb_id IS '按知识库查询索引';
COMMENT ON INDEX idx_embeddings_status IS '按状态过滤索引';

-- ============================================================
-- 9. 模型类型对照表
--     启动时从 config.yaml model_types 全量替换
-- ============================================================
CREATE TABLE IF NOT EXISTS model_types (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    code            SMALLINT    NOT NULL UNIQUE,
    name            VARCHAR(50) NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE model_types IS '模型类型对照表：code → 名称，启动时从 config.yaml 同步';
COMMENT ON COLUMN model_types.code IS '类型编码：1=embedding, 2=LLM...';
COMMENT ON COLUMN model_types.name IS '类型名称';

-- ============================================================
-- 10. 模型厂商表
--     Phase 3：启动时从 config.yaml model_providers 自动创建，用户只读
--     关系：model_providers 1:N default_model_config
-- ============================================================
CREATE TABLE IF NOT EXISTS model_providers (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name            VARCHAR(50)   NOT NULL UNIQUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

COMMENT ON TABLE model_providers      IS '模型厂商表：启动时从 config.yaml 自动创建，用户只读不可增删';
COMMENT ON COLUMN model_providers.name IS '厂商名（unique）：local / aliyun / openai / deepseek';

-- ============================================================
-- 10.1 默认模型配置表
--      Phase 3：启动时从 config.yaml model_providers.{provider}.models 自动创建
--      每个厂商下可有多个模型，存储各模型的默认参数（base_url、dimension）
--      用户创建 user_model_config 时以此为基础，可覆盖 base_url
-- ============================================================
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

COMMENT ON TABLE default_model_config                IS '默认模型配置表：启动时自动创建，用户只读。厂商→模型→默认参数';
COMMENT ON COLUMN default_model_config.provider      IS '所属厂商名，对应 model_providers.name';
COMMENT ON COLUMN default_model_config.model_name    IS '模型名：text-embedding-v1 / gpt-4o 等';
COMMENT ON COLUMN default_model_config.model_type    IS '1=embedding, 2=LLM, 3=Rerank';
COMMENT ON COLUMN default_model_config.base_url      IS 'API 地址（厂商默认，用户创建配置时可覆盖）';
COMMENT ON COLUMN default_model_config.dimension     IS 'embedding 输出维度，LLM 时 NULL';

-- ============================================================
-- 11. 用户模型配置表
--      Phase 3：用户在前端创建，选模型后自动带入 default_model_config 参数
--      base_url 可覆盖（自建代理/私有化部署等），api_key 由用户填写
--      向量化时 find_active_embedding() 查此表取 active 的配置
-- ============================================================
CREATE TABLE IF NOT EXISTS user_model_config (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    provider        VARCHAR(50)   NOT NULL,
    model_name      VARCHAR(200)  NOT NULL,
    model_type      SMALLINT      NOT NULL,
    base_url        VARCHAR(500),
    api_key         VARCHAR(500),
    dimension       INT,
    protocol        VARCHAR(20),              -- Phase 4.7：调用模式（协议），空 = 按厂商推断默认 openai
    temperature     DOUBLE PRECISION,         -- Phase 4.8：采样温度（空 = 未配置，Agent 未单独设置时生效）
    top_p           DOUBLE PRECISION,         -- Phase 4.8：核采样（空 = 未配置）
    max_tokens      INT,                      -- Phase 4.8：最大生成 token 数（空 = 厂商默认）
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_umc_user_id ON user_model_config(user_id);
CREATE INDEX IF NOT EXISTS idx_umc_type    ON user_model_config(model_type);

COMMENT ON TABLE user_model_config               IS '用户模型配置表：base_url=NULL 时使用 default_model_config 的默认值';
COMMENT ON COLUMN user_model_config.user_id      IS '所属用户 ID（多租户预留）';
COMMENT ON COLUMN user_model_config.provider     IS '厂商名，用于 EmbeddingService switch 分发';
COMMENT ON COLUMN user_model_config.model_name   IS '模型名，传给 SDK/API';
COMMENT ON COLUMN user_model_config.model_type   IS '1=embedding, 2=LLM, 3=Rerank';
COMMENT ON COLUMN user_model_config.base_url     IS 'API 地址。用户可覆盖（自建代理），NULL 则用 default 的';
COMMENT ON COLUMN user_model_config.api_key      IS 'API Key（阿里云 DashScope / OpenAI 等）';
COMMENT ON COLUMN user_model_config.dimension    IS '向量维度（embedding 用，LLM 为 NULL）';
COMMENT ON COLUMN user_model_config.protocol     IS '调用模式（协议）：openai；空 = 按厂商推断默认 openai（自定义厂商必填）';
COMMENT ON COLUMN user_model_config.temperature  IS '采样温度（模型级默认值，Agent 未单独设置时生效）';
COMMENT ON COLUMN user_model_config.top_p        IS '核采样（模型级默认值）';
COMMENT ON COLUMN user_model_config.max_tokens   IS '最大生成 token 数（空 = 厂商默认）';
COMMENT ON COLUMN user_model_config.is_active    IS '是否启用。向量化时只取 active 且 model_type=1 的';
COMMENT ON INDEX idx_umc_user_id                IS '按用户查询索引';
COMMENT ON INDEX idx_umc_type                   IS '按类型查询索引：快速找 embedding 或 LLM 配置';

-- knowledge_bases.user_model_config_id 外键（补建：knowledge_bases 建表早于 user_model_config，避免前向引用）
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_kb_umc') THEN
        ALTER TABLE knowledge_bases
            ADD CONSTRAINT fk_kb_umc FOREIGN KEY (user_model_config_id)
            REFERENCES user_model_config(id) ON DELETE SET NULL;
    END IF;
END $$;

-- ============================================================
-- 12. Agent 表（分类分表）
--      Phase 4：Agent 按类型分表存储（字段需求不同）
--      simple_rag_agents：简单 RAG Agent，仅 RAG 功能，知识库直接绑定
--      general_agents：综合 Agent，能力以工具列表注册（tools JSONB）
--      workflow：预留，MVP 不做
--      迁移来源：006（建表）→ 007（工具化）→ 008（分类分表）
-- ============================================================
CREATE TABLE IF NOT EXISTS simple_rag_agents (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID         NOT NULL REFERENCES users(id),
    name             VARCHAR(200) NOT NULL,
    description      TEXT,
    kb_id            UUID         NOT NULL REFERENCES knowledge_bases(id),
    llm_config_id    UUID         REFERENCES user_model_config(id) ON DELETE SET NULL,
    top_k            INT          NOT NULL DEFAULT 5,
    score_threshold  FLOAT        NOT NULL DEFAULT 0.3,
    system_prompt    TEXT         NOT NULL,
    -- 采样参数可空（Phase 4.8）：空 = 跟随模型配置（模型未配置时默认 0.7/0.9）
    temperature      FLOAT,
    top_p            FLOAT,
    max_tokens       INT,
    welcome_message  VARCHAR(500),
    -- Phase 4.5：总结模型配置（空 = 跟随对话模型）
    summary_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
    -- Phase 4.6：检索增强（独立开关，默认关闭）
    mqe_enabled          BOOLEAN NOT NULL DEFAULT FALSE,
    hyde_enabled         BOOLEAN NOT NULL DEFAULT FALSE,
    mqe_query_count      SMALLINT NOT NULL DEFAULT 3,
    rerank_enabled       BOOLEAN NOT NULL DEFAULT FALSE,
    enhance_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
    rerank_config_id     UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
    status           SMALLINT     NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_sra_user   ON simple_rag_agents(user_id);
CREATE INDEX IF NOT EXISTS idx_sra_kb     ON simple_rag_agents(kb_id);
CREATE INDEX IF NOT EXISTS idx_sra_status ON simple_rag_agents(status);

COMMENT ON TABLE simple_rag_agents IS '简单 RAG Agent 表：仅 RAG 功能，知识库直接绑定';
COMMENT ON COLUMN simple_rag_agents.user_id IS '创建者用户 ID';
COMMENT ON COLUMN simple_rag_agents.name IS 'Agent 名称';
COMMENT ON COLUMN simple_rag_agents.description IS '描述';
COMMENT ON COLUMN simple_rag_agents.kb_id IS '绑定的知识库 ID';
COMMENT ON COLUMN simple_rag_agents.llm_config_id IS 'LLM 模型配置 ID（user_model_config.model_type=2）';
COMMENT ON COLUMN simple_rag_agents.top_k IS '检索返回块数（默认取 config.yaml tools.default_top_k）';
COMMENT ON COLUMN simple_rag_agents.score_threshold IS '相似度阈值（默认取 config.yaml tools.default_score_threshold）';
COMMENT ON COLUMN simple_rag_agents.system_prompt IS '系统提示词（RAG 模板，可编辑）';
COMMENT ON COLUMN simple_rag_agents.temperature IS 'LLM 温度（空 = 跟随模型配置）';
COMMENT ON COLUMN simple_rag_agents.top_p IS 'LLM 核采样（空 = 跟随模型配置）';
COMMENT ON COLUMN simple_rag_agents.max_tokens IS '最大生成 token 数（空 = 跟随模型配置/厂商默认）';
COMMENT ON COLUMN simple_rag_agents.summary_llm_config_id IS '总结模型配置 ID（SummarizationMiddleware 用，空=跟随对话模型）';
COMMENT ON COLUMN simple_rag_agents.mqe_enabled IS '多查询扩展（MQE）：LLM 改写多个子问题多路召回（默认取 config.yaml tools.default_mqe_enabled）';
COMMENT ON COLUMN simple_rag_agents.hyde_enabled IS '假设文档嵌入（HyDE）：LLM 生成假设回答文档作为检索线索';
COMMENT ON COLUMN simple_rag_agents.mqe_query_count IS 'MQE 改写子问题数（2~5）';
COMMENT ON COLUMN simple_rag_agents.rerank_enabled IS 'Rerank 精排开关（默认取 config.yaml tools.default_rerank_enabled）';
COMMENT ON COLUMN simple_rag_agents.enhance_llm_config_id IS '增强 LLM 配置 ID（MQE 改写/HyDE 生成用，model_type=2，空=跟随对话模型）';
COMMENT ON COLUMN simple_rag_agents.rerank_config_id IS 'Rerank 模型配置 ID（model_type=3，空=用 config.yaml tools.rerank 全局默认）';
COMMENT ON COLUMN simple_rag_agents.welcome_message IS '欢迎语（Phase 5 浮窗使用）';
COMMENT ON COLUMN simple_rag_agents.status IS '0=禁用, 1=启用, 9=软删除';

CREATE TABLE IF NOT EXISTS general_agents (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID          NOT NULL REFERENCES users(id),
    name            VARCHAR(200)  NOT NULL,
    description     TEXT,
    llm_config_id   UUID          REFERENCES user_model_config(id) ON DELETE SET NULL,
    tools           JSONB         NOT NULL DEFAULT '[]'::jsonb,
    system_prompt   TEXT          NOT NULL,
    -- 采样参数可空（Phase 4.8）：空 = 跟随模型配置（模型未配置时默认 0.7/0.9）
    temperature     FLOAT,
    top_p           FLOAT,
    max_tokens      INT,
    welcome_message VARCHAR(500),
    -- Phase 4.5：总结模型配置（空 = 跟随对话模型）
    summary_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
    -- Phase 4.6：检索增强（Agent 级模型引用）
    enhance_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
    rerank_config_id     UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
    status          SMALLINT      NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_general_agents_user   ON general_agents(user_id);
CREATE INDEX IF NOT EXISTS idx_general_agents_status ON general_agents(status);

COMMENT ON TABLE general_agents IS '综合 Agent 表：能力以工具列表（tools JSONB）形式注册';
COMMENT ON COLUMN general_agents.user_id IS '创建者用户 ID';
COMMENT ON COLUMN general_agents.name IS 'Agent 名称';
COMMENT ON COLUMN general_agents.description IS '描述';
COMMENT ON COLUMN general_agents.llm_config_id IS 'LLM 模型配置 ID（user_model_config.model_type=2）';
COMMENT ON COLUMN general_agents.tools IS '工具配置列表：[{"type": "rag", "kb_id": "...", "top_k": 5, "score_threshold": 0.3}]';
COMMENT ON COLUMN general_agents.system_prompt IS '系统提示词（RAG 模板，可编辑）';
COMMENT ON COLUMN general_agents.temperature IS 'LLM 温度（空 = 跟随模型配置）';
COMMENT ON COLUMN general_agents.top_p IS 'LLM 核采样（空 = 跟随模型配置）';
COMMENT ON COLUMN general_agents.max_tokens IS '最大生成 token 数（空 = 跟随模型配置/厂商默认）';
COMMENT ON COLUMN general_agents.summary_llm_config_id IS '总结模型配置 ID（SummarizationMiddleware 用，空=跟随对话模型）';
COMMENT ON COLUMN general_agents.enhance_llm_config_id IS '增强 LLM 配置 ID（MQE 改写/HyDE 生成用，model_type=2，空=跟随对话模型）';
COMMENT ON COLUMN general_agents.rerank_config_id IS 'Rerank 模型配置 ID（model_type=3，空=用 config.yaml tools.rerank 全局默认）';
COMMENT ON COLUMN general_agents.welcome_message IS '欢迎语（Phase 5 浮窗使用）';
COMMENT ON COLUMN general_agents.status IS '0=禁用, 1=启用, 9=软删除';

-- ============================================================
-- 13. Agent 索引表
--      Phase 4：所有 Agent 的基础信息，id 与类型表共用主键
--      用途：用户 Agent 列表（单表 SQL 分页）/ 类型定位
--      创建 Agent 时事务内双写（索引表 + 类型表，同 id）
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_index (
    id          UUID PRIMARY KEY,
    user_id     UUID         NOT NULL REFERENCES users(id),
    type        VARCHAR(20)  NOT NULL,
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    status      SMALLINT     NOT NULL DEFAULT 1,
    rate_limit_per_min     INTEGER NOT NULL DEFAULT 60,
    allowed_domains        JSONB    NOT NULL DEFAULT '[]',
    anonymous_retention_days INTEGER NOT NULL DEFAULT 30,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agent_index_user   ON agent_index(user_id);
CREATE INDEX IF NOT EXISTS idx_agent_index_type   ON agent_index(type);
CREATE INDEX IF NOT EXISTS idx_agent_index_status ON agent_index(status);

COMMENT ON TABLE agent_index IS 'Agent 索引表：所有 Agent 的基础信息，id 与类型表共用主键（simple_rag_agents / general_agents）';
COMMENT ON COLUMN agent_index.id IS 'Agent ID（与类型表主键共用）';
COMMENT ON COLUMN agent_index.user_id IS '创建者用户 ID';
COMMENT ON COLUMN agent_index.type IS 'Agent 类型：simple_rag / general / workflow（预留）';
COMMENT ON COLUMN agent_index.name IS 'Agent 名称（冗余，列表查询免 join 类型表）';
COMMENT ON COLUMN agent_index.description IS '描述（冗余）';
COMMENT ON COLUMN agent_index.status IS '0=禁用, 1=启用, 9=软删除';
COMMENT ON COLUMN agent_index.rate_limit_per_min IS '公开接口限流（IP+agent 维度，次/分钟）';
COMMENT ON COLUMN agent_index.allowed_domains IS '嵌入域名白名单，空数组=不限制';
COMMENT ON COLUMN agent_index.anonymous_retention_days IS '匿名会话保留天数（超期无活动惰性清理）';

-- ============================================================
-- 13.5 Agent 嵌入密钥表（Phase 5）
--      只存 SHA-256 哈希；明文仅生成时返回一次
-- ============================================================
CREATE TABLE IF NOT EXISTS agent_api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id     UUID NOT NULL REFERENCES agent_index(id) ON DELETE CASCADE,
    key_hash     VARCHAR(64) NOT NULL,
    key_preview  VARCHAR(20),
    name         VARCHAR(100),
    enabled      SMALLINT NOT NULL DEFAULT 1,
    last_used_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_agent_api_keys_agent_id ON agent_api_keys(agent_id);
COMMENT ON TABLE agent_api_keys IS 'Agent 嵌入密钥表（只存哈希 + 前缀预览）';
COMMENT ON COLUMN agent_api_keys.id IS '密钥主键';
COMMENT ON COLUMN agent_api_keys.agent_id IS '归属 Agent ID（级联删除）';
COMMENT ON COLUMN agent_api_keys.key_hash IS 'SHA-256 哈希（单向，不可反推明文）';
COMMENT ON COLUMN agent_api_keys.key_preview IS '明文前缀预览（如 pin_AbC123...，非明文，仅列表辨识用）';
COMMENT ON COLUMN agent_api_keys.name IS '备注（如：公司官网客服）';
COMMENT ON COLUMN agent_api_keys.enabled IS '1=启用 0=禁用';
COMMENT ON COLUMN agent_api_keys.last_used_at IS '最后使用时间（公开接口鉴权成功后更新）';
COMMENT ON COLUMN agent_api_keys.created_at IS '创建时间';
COMMENT ON COLUMN agent_api_keys.updated_at IS '最后更新时间';

-- ============================================================
-- 14. 会话表（Phase 4.5）
--      id 即 LangGraph checkpoint 的 thread_id
--      checkpoint 表由 AsyncPostgresSaver.setup() 自动创建,不在此建
-- ============================================================
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID REFERENCES users(id) ON DELETE CASCADE,
    agent_id    UUID NOT NULL REFERENCES agent_index(id),
    client_id   VARCHAR(64),
    title       VARCHAR(100),
    messages    JSONB NOT NULL DEFAULT '[]'::jsonb,
    status      SMALLINT NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS ix_conversations_agent_id ON conversations(agent_id);
CREATE INDEX IF NOT EXISTS ix_conversations_client_id ON conversations(client_id);
CREATE INDEX IF NOT EXISTS ix_conversations_agent_client ON conversations(agent_id, client_id);
COMMENT ON TABLE conversations IS '会话表：id 即 checkpoint thread_id；匿名会话 user_id 空 + client_id 非空';
COMMENT ON COLUMN conversations.id IS '会话 ID（= LangGraph checkpoint thread_id）';
COMMENT ON COLUMN conversations.user_id IS '归属用户 ID（匿名会话为空）';
COMMENT ON COLUMN conversations.agent_id IS '归属 Agent ID';
COMMENT ON COLUMN conversations.client_id IS '匿名访客标识（登录会话为空）';
COMMENT ON COLUMN conversations.title IS '会话标题（首轮对话自动用第一条用户消息前 10 字命名）';
COMMENT ON COLUMN conversations.status IS '1=启用, 9=软删除';
COMMENT ON COLUMN conversations.messages IS '会话消息 JSONB 数组：[{role, content, citations, created_at}]，写入用 || 原子追加';
COMMENT ON COLUMN conversations.created_at IS '创建时间';
COMMENT ON COLUMN conversations.updated_at IS '最后更新时间（含 checkpoint 写入）';

-- ============================================================
-- 15. 会话消息（Phase 4.5 → 013 改版）
--      消息不再单独建表：存于 conversations.messages JSONB（每会话一条记录）
--      写入一律 SQL 原子追加（|| 拼接），禁止应用层读改写
-- ============================================================

-- ============================================================
-- 17. 用户自定义厂商表（Phase 4.9）
--      前端可增删改，效果等同 config.yaml 预置厂商（带调用模式）
--      与预置 model_providers 分离（seed 清空逻辑不误删用户数据）
-- ============================================================
CREATE TABLE IF NOT EXISTS user_providers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(50) NOT NULL,
    protocol    VARCHAR(20) NOT NULL DEFAULT 'openai',
    description VARCHAR(200),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_providers_name UNIQUE (user_id, name)
);

COMMENT ON TABLE user_providers IS '用户自定义厂商表：前端可增删改，效果等同 config.yaml 预置厂商（带调用模式 protocol）';
COMMENT ON COLUMN user_providers.user_id IS '所属用户 ID';
COMMENT ON COLUMN user_providers.name IS '厂商名（同用户下唯一）';
COMMENT ON COLUMN user_providers.protocol IS '调用模式（协议）：openai 等';
COMMENT ON COLUMN user_providers.description IS '备注说明';

-- ============================================================
-- 16. 通用系统设置表（014）
--      JSON 配置存储；脱敏规则等系统级配置的唯一事实来源
-- ============================================================
CREATE TABLE IF NOT EXISTS system_settings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(100) NOT NULL UNIQUE,
    value       JSONB NOT NULL,
    description VARCHAR(200),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE system_settings IS '通用系统设置表（JSON 配置存储）';
COMMENT ON COLUMN system_settings.key IS '设置项标识（如 logging.redact_rules）';
COMMENT ON COLUMN system_settings.value IS '配置值（任意 JSON 结构，后端自行解析）';
