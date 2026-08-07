-- ============================================================
-- 迁移 001：文档表增加切片/向量化状态字段
-- 版本  : v0.2 → v0.3
-- 日期  : 2025-08-06
-- 说明  : Phase 3 预备，给 documents 表增加 is_chunked 和
--         is_vectorized 两个 SMALLINT 状态字段，默认 0
--         状态：-1=失败, 0=未完成, 1=已完成, 2=进行中
-- 回滚  : ALTER TABLE documents DROP COLUMN is_chunked, DROP COLUMN is_vectorized;
-- ============================================================

ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_chunked    SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_vectorized SMALLINT NOT NULL DEFAULT 0;

COMMENT ON COLUMN documents.is_chunked    IS '切片状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON COLUMN documents.is_vectorized IS '向量化状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
