-- ============================================================
-- 迁移 009：Agent 表模型配置外键改 ON DELETE SET NULL
-- ============================================================
-- 版本  : v0.7.1
-- 日期  : 2026-08-08
-- 依赖  : 迁移 008（agent_index 已存在）
-- ============================================================
-- 概述
--   simple_rag_agents / general_agents 的 llm_config_id 外键原为默认 RESTRICT：
--   删除模型配置时，即使引用方 Agent 已软删除（status=9）也会被阻塞。
--   （knowledge_bases.user_model_config_id 在建表时已是 ON DELETE SET NULL，无需改动）
--
--   本次迁移将两张 Agent 表的外键改为 ON DELETE SET NULL，并去掉 NOT NULL：
--     删除配置 → 引用记录的 llm_config_id 自动置 NULL（配置删除后 Agent 无 LLM 配置为合法状态）
--   （配合引用检查只统计未删除记录：真正在用的拦截 409，软删的自动解除）
--
-- 回滚
--   ALTER TABLE simple_rag_agents ALTER COLUMN llm_config_id SET NOT NULL;
--   ALTER TABLE simple_rag_agents DROP CONSTRAINT simple_rag_agents_llm_config_id_fkey;
--   ALTER TABLE simple_rag_agents ADD CONSTRAINT simple_rag_agents_llm_config_id_fkey
--       FOREIGN KEY (llm_config_id) REFERENCES user_model_config(id);
--   （general_agents 同理）
-- ============================================================

-- 1. llm_config_id 允许 NULL（配置删除后 SET NULL 需要）
ALTER TABLE simple_rag_agents ALTER COLUMN llm_config_id DROP NOT NULL;
ALTER TABLE general_agents ALTER COLUMN llm_config_id DROP NOT NULL;

-- 2. 外键改为 ON DELETE SET NULL
ALTER TABLE simple_rag_agents DROP CONSTRAINT simple_rag_agents_llm_config_id_fkey;
ALTER TABLE simple_rag_agents ADD CONSTRAINT simple_rag_agents_llm_config_id_fkey
    FOREIGN KEY (llm_config_id) REFERENCES user_model_config(id) ON DELETE SET NULL;

ALTER TABLE general_agents DROP CONSTRAINT general_agents_llm_config_id_fkey;
ALTER TABLE general_agents ADD CONSTRAINT general_agents_llm_config_id_fkey
    FOREIGN KEY (llm_config_id) REFERENCES user_model_config(id) ON DELETE SET NULL;
