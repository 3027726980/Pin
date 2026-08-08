-- ============================================================
-- 迁移 006：Agent 工具化重构（tools JSONB，移除 kb_id/top_k/score_threshold）
-- ============================================================
-- 版本  : v0.5.1
-- 日期  : 2026-08-08
-- 依赖  : 迁移 006（agents 表已存在）
-- ============================================================
-- 概述
--   RAG 从独立服务改为 Agent 的工具：工具自带配置，Agent 保存工具列表。
--   原 agents.kb_id / top_k / score_threshold 移入 tools JSONB：
--     [{"type": "rag", "kb_id": "...", "top_k": 5, "score_threshold": 0.3}]
--   temperature / top_p（LLM 采样参数）保留在 agents 表。
--
-- 回滚
--   ALTER TABLE agents ADD COLUMN kb_id UUID REFERENCES knowledge_bases(id);
--   ALTER TABLE agents ADD COLUMN top_k INT NOT NULL DEFAULT 5;
--   ALTER TABLE agents ADD COLUMN score_threshold FLOAT NOT NULL DEFAULT 0.3;
--   ALTER TABLE agents DROP COLUMN IF EXISTS tools;
-- ============================================================

-- 1. 新增 tools 字段（工具配置列表，JSONB）
ALTER TABLE agents ADD COLUMN IF NOT EXISTS tools JSONB NOT NULL DEFAULT '[]'::jsonb;

-- 2. 移除迁移到工具配置的旧字段（DROP COLUMN 自动清理 FK 约束与索引）
ALTER TABLE agents DROP COLUMN IF EXISTS kb_id;
ALTER TABLE agents DROP COLUMN IF EXISTS top_k;
ALTER TABLE agents DROP COLUMN IF EXISTS score_threshold;

COMMENT ON COLUMN agents.tools IS '工具配置列表：[{"type": "rag", "kb_id": "...", "top_k": 5, "score_threshold": 0.3}]';
