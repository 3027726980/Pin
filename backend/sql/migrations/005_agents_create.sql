-- ============================================================
-- 迁移 005：Phase 4 Agent 表
-- ============================================================
-- 版本  : v0.5
-- 日期  : 2026-08-08
-- 依赖  : 迁移 003（knowledge_bases / user_model_config 已存在）
-- ============================================================
-- 概述
--   新增 agents 表：Agent 绑定一个知识库（一对一）+ 一个 LLM 模型配置，
--   保存 RAG 对话所需的检索参数（top_k / score_threshold）和采样参数
--   （temperature / top_p）。
--
-- 回滚
--   DROP TABLE IF EXISTS agents;
-- ============================================================

CREATE TABLE IF NOT EXISTS agents (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID         NOT NULL REFERENCES users(id),
    name             VARCHAR(200) NOT NULL,
    description      TEXT,
    kb_id            UUID         NOT NULL REFERENCES knowledge_bases(id),
    llm_config_id    UUID         NOT NULL REFERENCES user_model_config(id),
    system_prompt    TEXT         NOT NULL,
    top_k            INT          NOT NULL DEFAULT 5,
    score_threshold  FLOAT        NOT NULL DEFAULT 0.3,
    temperature      FLOAT        NOT NULL DEFAULT 0.7,
    top_p            FLOAT        NOT NULL DEFAULT 0.9,
    welcome_message  VARCHAR(500),
    status           SMALLINT     NOT NULL DEFAULT 1,
    created_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_agents_user   ON agents(user_id);
CREATE INDEX IF NOT EXISTS idx_agents_kb     ON agents(kb_id);
CREATE INDEX IF NOT EXISTS idx_agents_status ON agents(status);

COMMENT ON TABLE agents IS 'Agent 表：绑定一个知识库 + 一个 LLM 模型配置的可对话实体';
COMMENT ON COLUMN agents.user_id IS '创建者用户 ID';
COMMENT ON COLUMN agents.name IS 'Agent 名称';
COMMENT ON COLUMN agents.description IS '描述';
COMMENT ON COLUMN agents.kb_id IS '绑定知识库 ID（一对一）';
COMMENT ON COLUMN agents.llm_config_id IS 'LLM 模型配置 ID（user_model_config.model_type=2）';
COMMENT ON COLUMN agents.system_prompt IS '系统提示词（RAG 模板，可编辑）';
COMMENT ON COLUMN agents.top_k IS '检索返回块数';
COMMENT ON COLUMN agents.score_threshold IS '相似度阈值（余弦相似度，低于则丢弃）';
COMMENT ON COLUMN agents.temperature IS 'LLM 温度';
COMMENT ON COLUMN agents.top_p IS 'LLM 核采样';
COMMENT ON COLUMN agents.welcome_message IS '欢迎语（Phase 5 浮窗使用）';
COMMENT ON COLUMN agents.status IS '0=禁用, 1=启用, 9=软删除';
