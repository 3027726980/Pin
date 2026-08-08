-- ============================================================
-- 迁移 008：Agent 索引表（agent_index）
-- ============================================================
-- 版本  : v0.7
-- 日期  : 2026-08-08
-- 依赖  : 迁移 007（simple_rag_agents / general_agents 已存在）
-- ============================================================
-- 概述
--   agent_index：所有 Agent 的基础信息索引表（id 与类型表共用主键）。
--   用途：
--     1. 查询用户拥有的 Agent 列表 → 单表 SQL 分页（替代多表内存合并）
--     2. 定位 Agent 类型（详情/对话）→ 查索引表拿 type，再查对应类型表
--   设计：
--     - 只存基础信息（id / user_id / type / name / description / status）
--     - 创建 Agent 时事务内双写（索引表 + 类型表，同 id）
--     - 新增 Agent 类型（如 workflow）= 新类型表 + 索引表插记录，列表/定位零改动
--
-- 回滚
--   DROP TABLE IF EXISTS agent_index;
-- ============================================================

CREATE TABLE IF NOT EXISTS agent_index (
    id          UUID PRIMARY KEY,
    user_id     UUID         NOT NULL REFERENCES users(id),
    type        VARCHAR(20)  NOT NULL,
    name        VARCHAR(200) NOT NULL,
    description TEXT,
    status      SMALLINT     NOT NULL DEFAULT 1,
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
COMMENT ON INDEX idx_agent_index_user IS '按用户查询索引（用户 Agent 列表）';
COMMENT ON INDEX idx_agent_index_type IS '按类型筛选索引';
COMMENT ON INDEX idx_agent_index_status IS '按状态过滤索引';

-- 回填现有数据（simple_rag / general 类型表 → 索引表）
INSERT INTO agent_index (id, user_id, type, name, description, status, created_at, updated_at)
SELECT id, user_id, 'simple_rag', name, description, status, created_at, updated_at
FROM simple_rag_agents;

INSERT INTO agent_index (id, user_id, type, name, description, status, created_at, updated_at)
SELECT id, user_id, 'general', name, description, status, created_at, updated_at
FROM general_agents;
