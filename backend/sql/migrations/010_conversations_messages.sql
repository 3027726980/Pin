-- 010_conversations_messages.sql
-- Phase 4.5: 会话实体 + 消息留痕 + Agent 总结模型配置
--
-- 注:checkpoint 相关表(checkpoints / checkpoint_blobs / checkpoint_writes / checkpoint_migrations)
--     由 langgraph-checkpoint-postgres 的 AsyncPostgresSaver.setup() 自动创建,无需在此建表。

CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id),
    agent_id    UUID NOT NULL REFERENCES agent_index(id),
    title       VARCHAR(100),
    status      INTEGER NOT NULL DEFAULT 1,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_conversations_user_id ON conversations(user_id);
CREATE INDEX IF NOT EXISTS ix_conversations_agent_id ON conversations(agent_id);

CREATE TABLE IF NOT EXISTS messages (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID NOT NULL REFERENCES conversations(id),
    role            VARCHAR(20) NOT NULL,
    content         TEXT NOT NULL,
    citations       JSONB,
    status          INTEGER NOT NULL DEFAULT 1,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_id ON messages(conversation_id);

ALTER TABLE simple_rag_agents
    ADD COLUMN IF NOT EXISTS summary_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL;
ALTER TABLE general_agents
    ADD COLUMN IF NOT EXISTS summary_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL;
