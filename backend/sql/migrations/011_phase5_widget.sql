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

-- ============================================================
-- 注释补全（幂等，重跑不报错）
-- ============================================================

COMMENT ON TABLE agent_api_keys IS 'Agent 嵌入密钥表（只存 SHA-256 哈希，明文仅生成时返回一次）';
COMMENT ON COLUMN agent_api_keys.id IS '密钥主键';
COMMENT ON COLUMN agent_api_keys.agent_id IS '归属 Agent ID（级联删除）';
COMMENT ON COLUMN agent_api_keys.key_hash IS 'SHA-256 哈希（单向，不可反推明文）';
COMMENT ON COLUMN agent_api_keys.name IS '备注（如：公司官网客服）';
COMMENT ON COLUMN agent_api_keys.enabled IS '1=启用 0=禁用';
COMMENT ON COLUMN agent_api_keys.last_used_at IS '最后使用时间（公开接口鉴权成功后更新）';
COMMENT ON COLUMN agent_api_keys.created_at IS '创建时间';
COMMENT ON COLUMN agent_api_keys.updated_at IS '最后更新时间';

COMMENT ON COLUMN agent_index.rate_limit_per_min IS '公开接口限流（IP+agent 维度，次/分钟）';
COMMENT ON COLUMN agent_index.allowed_domains IS '嵌入域名白名单，空数组=不限制';
COMMENT ON COLUMN agent_index.anonymous_retention_days IS '匿名会话保留天数（超期无活动惰性清理）';

COMMENT ON COLUMN conversations.client_id IS '匿名访客标识（登录会话为空；匿名会话 user_id 空 + client_id 非空）';
