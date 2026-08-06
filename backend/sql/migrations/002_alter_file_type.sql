-- ============================================================
-- 迁移 002：文档表 file_type 字段改为可空 + 存后缀而非 MIME
-- 版本  : v0.3
-- 日期  : 2025-08-06
-- 说明  : file_type 从 MIME 类型改为文件后缀（如 .pdf），无后缀时为 NULL
-- 回滚  : ALTER TABLE documents ALTER COLUMN file_type SET NOT NULL;
-- ============================================================

ALTER TABLE documents ALTER COLUMN file_type DROP NOT NULL;
ALTER TABLE documents ALTER COLUMN file_type TYPE VARCHAR(100);

COMMENT ON COLUMN documents.file_type IS '文件后缀，如 .pdf，无后缀则为 NULL';
