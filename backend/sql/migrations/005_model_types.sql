-- ============================================================
-- 迁移 005: 新增 model_types 表
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
