-- ============================================================
-- 迁移 003：Phase 3 文档处理表
-- 版本  : v0.4
-- 日期  : 2025-08-07
-- 说明  :
--   1. documents 新增 content + is_parsed 字段
--   2. knowledge_bases 新增分块/embedding 配置字段
--   3. 新建 chunks、embeddings、model_config 表
-- 回滚  :
--   ALTER TABLE documents DROP COLUMN content, DROP COLUMN is_parsed;
--   ALTER TABLE knowledge_bases DROP COLUMN chunk_size, ...;
--   DROP TABLE embeddings, chunks, model_config;
-- ============================================================

-- 0. documents 新增 content + 解析状态
ALTER TABLE documents ADD COLUMN IF NOT EXISTS content TEXT;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_parsed
    SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN documents.content IS '解析后的完整纯文本';
COMMENT ON COLUMN documents.is_parsed IS '解析状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';

-- 1. knowledge_bases 新增分块/embedding 配置
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS chunk_size
    INT NOT NULL DEFAULT 800;
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS chunk_overlap
    INT NOT NULL DEFAULT 150;
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS chunk_separators
    VARCHAR(300) NOT NULL DEFAULT E'\n##,\n###,\n,。,., ';
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS embedding_model
    VARCHAR(100) NOT NULL DEFAULT 'text-embedding-3-small';
ALTER TABLE knowledge_bases ADD COLUMN IF NOT EXISTS embedding_dimension
    INT NOT NULL DEFAULT 1536;

COMMENT ON COLUMN knowledge_bases.chunk_size IS '分块大小（字符数），默认 800';
COMMENT ON COLUMN knowledge_bases.chunk_overlap IS '相邻块重叠字符数，默认 150';
COMMENT ON COLUMN knowledge_bases.chunk_separators IS '递归分隔符（逗号分隔）';
COMMENT ON COLUMN knowledge_bases.embedding_model IS '选用的 Embedding 模型';
COMMENT ON COLUMN knowledge_bases.embedding_dimension IS '模型输出维度';

-- 2. 分块表
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

COMMENT ON TABLE chunks IS '分块表：status: -1=失败,0=未完成,1=已完成,2=进行中';

-- 3. 向量表
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

COMMENT ON TABLE embeddings IS '向量表：vector(2048)，小维度零填充';

-- 4. 模型配置表
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

COMMENT ON TABLE model_config IS '模型配置表：model_type: 1=embedding, 2=LLM';
