-- 011_phase5_widget.sql
-- Phase 5: 嵌入窗口（widget）
--
-- 1. agent_api_keys 表：Agent 嵌入密钥（只存哈希）
-- 2. agent_index 表新增治理参数（限流 / 域名白名单 / 匿名会话保留天数）
-- 3. conversations 表新增 client_id（匿名访客标识），user_id 改为可空

-- 1. Agent 嵌入密钥表
CREATE TABLE IF NOT EXISTS agent_api_keys (
    id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id     UUID NOT NULL REFERENCES agent_index(id) ON DELETE CASCADE,
    key_hash     VARCHAR(64) NOT NULL,
    name         VARCHAR(100),
    enabled      INTEGER NOT NULL DEFAULT 1,
    last_used_at TIMESTAMPTZ,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_agent_api_keys_agent_id ON agent_api_keys(agent_id);

-- 2. agent_index 治理参数（公开接口 / 嵌入场景，数据库动态可改）
ALTER TABLE agent_index
    ADD COLUMN IF NOT EXISTS rate_limit_per_min INTEGER NOT NULL DEFAULT 60,
    ADD COLUMN IF NOT EXISTS allowed_domains JSONB NOT NULL DEFAULT '[]',
    ADD COLUMN IF NOT EXISTS anonymous_retention_days INTEGER NOT NULL DEFAULT 30;

-- 3. conversations 匿名访客标识（匿名会话：user_id 空 + client_id 非空）
ALTER TABLE conversations
    ADD COLUMN IF NOT EXISTS client_id VARCHAR(64),
    ALTER COLUMN user_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS ix_conversations_client_id ON conversations(client_id);
CREATE INDEX IF NOT EXISTS ix_conversations_agent_client ON conversations(agent_id, client_id);
