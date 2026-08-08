-- ============================================================
-- 迁移 007：Agent 分类分表（simple_rag_agents + general_agents）
-- ============================================================
-- 版本  : v0.6
-- 日期  : 2026-08-08
-- 依赖  : 迁移 007（agents 表为工具化结构）
-- ============================================================
-- 概述
--   Agent 按类型分表存储（字段需求不同）：
--     1. simple_rag_agents：简单 RAG Agent，仅 RAG 功能，知识库直接绑定
--        （kb_id / top_k / score_threshold 为表字段）
--     2. general_agents：综合 Agent，能力以工具列表注册
--        （tools JSONB），原 agents 表重命名而来，数据保留
--   Workflow Agent（workflow）MVP 不做，后续新增表即可。
--
-- 回滚
--   ALTER TABLE general_agents RENAME TO agents;
--   DROP TABLE IF EXISTS simple_rag_agents;
-- ============================================================

-- 1. agents → general_agents（保留历史数据），索引改名
ALTER TABLE agents RENAME TO general_agents;
ALTER INDEX idx_agents_user   RENAME TO idx_general_agents_user;
ALTER INDEX idx_agents_status RENAME TO idx_general_agents_status;

-- 1.1 约束/主键索引改名（表改名后约束名保持 agents_*，统一为 general_agents_*）
ALTER TABLE general_agents RENAME CONSTRAINT agents_pkey TO general_agents_pkey;
ALTER INDEX agents_pkey RENAME TO general_agents_pkey;
ALTER TABLE general_agents RENAME CONSTRAINT agents_user_id_fkey TO general_agents_user_id_fkey;
ALTER TABLE general_agents RENAME CONSTRAINT agents_llm_config_id_fkey TO general_agents_llm_config_id_fkey;

COMMENT ON TABLE general_agents IS '综合 Agent 表：能力以工具列表（tools JSONB）形式注册';

-- 2. 新建 simple_rag_agents 表（简单 RAG Agent，仅 RAG 功能）
CREATE TABLE IF NOT EXISTS simple_rag_agents (
    id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    user_id          UUID         NOT NULL REFERENCES users(id),
    name             VARCHAR(200) NOT NULL,
    description      TEXT,
    kb_id            UUID         NOT NULL REFERENCES knowledge_bases(id),
    llm_config_id    UUID         NOT NULL REFERENCES user_model_config(id),
    top_k            INT          NOT NULL DEFAULT 5,
    score_threshold  FLOAT        NOT NULL DEFAULT 0.3,
    system_prompt    TEXT         NOT NULL,
    temperature      FLOAT        NOT NULL DEFAULT 0.7,
    top_p            FLOAT        NOT NULL DEFAULT 0.9,
    welcome_message  VARCHAR(500),
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
COMMENT ON COLUMN simple_rag_agents.temperature IS 'LLM 温度';
COMMENT ON COLUMN simple_rag_agents.top_p IS 'LLM 核采样';
COMMENT ON COLUMN simple_rag_agents.welcome_message IS '欢迎语（Phase 5 浮窗使用）';
COMMENT ON COLUMN simple_rag_agents.status IS '0=禁用, 1=启用, 9=软删除';
