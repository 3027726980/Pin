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

-- ============================================================
-- 注释补全（幂等，重跑不报错）
-- ============================================================

COMMENT ON TABLE conversations IS '会话表：id 即 checkpoint thread_id（对话记忆的归属单元）';
COMMENT ON COLUMN conversations.id IS '会话 ID（= LangGraph checkpoint thread_id）';
COMMENT ON COLUMN conversations.user_id IS '归属用户 ID';
COMMENT ON COLUMN conversations.agent_id IS '归属 Agent ID';
COMMENT ON COLUMN conversations.title IS '会话标题（首轮对话自动用第一条用户消息前 10 字命名）';
COMMENT ON COLUMN conversations.status IS '1=启用, 9=软删除';
COMMENT ON COLUMN conversations.created_at IS '创建时间';
COMMENT ON COLUMN conversations.updated_at IS '最后更新时间（含 checkpoint 写入）';

COMMENT ON TABLE messages IS '会话消息表：历史留痕（与 checkpoint 解耦，历史查看数据源）';
COMMENT ON COLUMN messages.id IS '消息主键';
COMMENT ON COLUMN messages.conversation_id IS '归属会话 ID（= thread_id）';
COMMENT ON COLUMN messages.role IS '消息角色：user / assistant';
COMMENT ON COLUMN messages.content IS '消息内容';
COMMENT ON COLUMN messages.citations IS '引用来源 JSONB：[{chunk_id, document_name, content, score}]';
COMMENT ON COLUMN messages.status IS '1=启用, 9=软删除';
COMMENT ON COLUMN messages.created_at IS '创建时间';
