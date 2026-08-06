-- ============================================================
-- 迁移 001：文档表增加切片/向量化标记字段
-- 版本  : v0.2 → v0.3
-- 日期  : 2025-08-06
-- 说明  : Phase 3 预备，给 documents 表增加 is_chunked 和
--         is_vectorized 两个布尔字段，默认 FALSE
-- 回滚  : ALTER TABLE documents DROP COLUMN is_chunked, DROP COLUMN is_vectorized;
-- ============================================================

ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_chunked    BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_vectorized BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN documents.is_chunked    IS '是否已完成切片';
COMMENT ON COLUMN documents.is_vectorized IS '是否已完成向量化';
