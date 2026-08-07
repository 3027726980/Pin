-- ============================================================
-- Pin 数据库初始化脚本
-- 数据库: PostgreSQL 17 + pgvector
-- 版本  : v0.2 (Phase 2)
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
--     Phase 2：存储知识库的基本信息 + 上传约束
-- ============================================================
CREATE TABLE IF NOT EXISTS knowledge_bases (
    id                  UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id             UUID        NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name                VARCHAR(200) NOT NULL,
    description         TEXT,
    allowed_extensions  VARCHAR(500),
    max_file_size       BIGINT      NOT NULL DEFAULT 104857600,
    allow_multiple      BOOLEAN     NOT NULL DEFAULT TRUE,
    chunk_size          INT         NOT NULL DEFAULT 800,
    chunk_overlap       INT         NOT NULL DEFAULT 150,
    chunk_separators    VARCHAR(300) NOT NULL DEFAULT '
##,
###,
,。,., ',
    embedding_model     VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small',
    embedding_dimension INT         NOT NULL DEFAULT 1536,
    status              SMALLINT    NOT NULL DEFAULT 1,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
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
COMMENT ON COLUMN knowledge_bases.status IS '0=禁用, 1=启用, 9=逻辑删除';
COMMENT ON COLUMN knowledge_bases.created_at IS '记录创建时间';
COMMENT ON COLUMN knowledge_bases.updated_at IS '记录最后更新时间';
COMMENT ON COLUMN knowledge_bases.chunk_size IS '分块大小（字符数），默认 800';
COMMENT ON COLUMN knowledge_bases.chunk_overlap IS '相邻块重叠字符数，默认 150';
COMMENT ON COLUMN knowledge_bases.chunk_separators IS '递归分隔符（逗号分隔），默认 \n##,\n###,\n,。,., ';
COMMENT ON COLUMN knowledge_bases.embedding_model IS '选用的 Embedding 模型，默认 text-embedding-3-small';
COMMENT ON COLUMN knowledge_bases.embedding_dimension IS '模型输出维度，默认 1536';
COMMENT ON INDEX idx_kb_user_id IS '按创建者查询索引，列出用户的知识库时使用';
COMMENT ON INDEX idx_kb_status IS '按状态过滤索引，查询时排除已删除记录';

-- ============================================================
-- 6. 文档表
--     Phase 2：存储上传到知识库中的文档元信息
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
    status          SMALLINT      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_chunks_doc_id  ON chunks(document_id);
CREATE INDEX IF NOT EXISTS idx_chunks_kb_id   ON chunks(kb_id);
CREATE INDEX IF NOT EXISTS idx_chunks_status  ON chunks(status);

COMMENT ON TABLE chunks IS '分块表：存储文档分块后的文本片段，status: -1=失败,0=未完成,1=已完成,2=进行中';
COMMENT ON COLUMN chunks.document_id IS '所属文档 ID';
COMMENT ON COLUMN chunks.kb_id IS '所属知识库 ID（冗余加速检索）';
COMMENT ON COLUMN chunks.chunk_index IS '块序号，同一文档内从 0 递增';
COMMENT ON COLUMN chunks.content IS '分块文本内容';
COMMENT ON COLUMN chunks.metadata IS '来源标题、页码等元信息';
COMMENT ON COLUMN chunks.status IS '-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON INDEX idx_chunks_doc_id IS '按文档查询索引';
COMMENT ON INDEX idx_chunks_kb_id IS '按知识库查询索引';
COMMENT ON INDEX idx_chunks_status IS '按状态过滤索引';

-- ============================================================
-- 8. 向量表
--     Phase 3：存储分块文本的 Embedding 向量，统一 vector(2048)
-- ============================================================
CREATE TABLE IF NOT EXISTS embeddings (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    chunk_id        UUID          NOT NULL UNIQUE REFERENCES chunks(id) ON DELETE CASCADE,
    kb_id           UUID          NOT NULL REFERENCES knowledge_bases(id) ON DELETE CASCADE,
    embedding       vector(2048),
    status          SMALLINT      NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_embeddings_chunk_id ON embeddings(chunk_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_kb_id    ON embeddings(kb_id);
CREATE INDEX IF NOT EXISTS idx_embeddings_status   ON embeddings(status);

COMMENT ON TABLE embeddings IS '向量表：存储分块文本的 Embedding 向量，整体 vector(2048)，小维度模型零填充';
COMMENT ON COLUMN embeddings.chunk_id IS '关联的分块 ID，一一对应';
COMMENT ON COLUMN embeddings.kb_id IS '所属知识库 ID（冗余加速检索）';
COMMENT ON COLUMN embeddings.embedding IS '向量数据，固定 2048 维（小维度零填充）';
COMMENT ON COLUMN embeddings.status IS '-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON INDEX idx_embeddings_chunk_id IS '按分块查询索引';
COMMENT ON INDEX idx_embeddings_kb_id IS '按知识库查询索引';
COMMENT ON INDEX idx_embeddings_status IS '按状态过滤索引';

-- ============================================================
-- 9. 模型配置表
--     Phase 3：统一管理 API Key 和模型配置（embedding + LLM）
-- ============================================================
CREATE TABLE IF NOT EXISTS model_config (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id         UUID          NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    model_type      SMALLINT      NOT NULL,
    provider        VARCHAR(50)   NOT NULL,
    model_name      VARCHAR(200)  NOT NULL,
    key_value       VARCHAR(500),
    is_active       BOOLEAN       NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_model_config_user_id ON model_config(user_id);
CREATE INDEX IF NOT EXISTS idx_model_config_type    ON model_config(model_type);

COMMENT ON TABLE model_config IS '模型配置表：统一管理 Embedding 和 LLM 的 API Key 和模型配置';
COMMENT ON COLUMN model_config.user_id IS '所属用户 ID';
COMMENT ON COLUMN model_config.model_type IS '1=embedding, 2=LLM（3~9 预留）';
COMMENT ON COLUMN model_config.provider IS '服务商：openai / ollama';
COMMENT ON COLUMN model_config.model_name IS '模型名称：text-embedding-3-small / gpt-4o 等';
COMMENT ON COLUMN model_config.key_value IS 'API Key（加密存储）';
COMMENT ON COLUMN model_config.is_active IS '是否启用';
COMMENT ON INDEX idx_model_config_user_id IS '按用户查询索引';
COMMENT ON INDEX idx_model_config_type IS '按类型查询索引';
