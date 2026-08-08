-- ============================================================
-- 迁移 001：文档表字段修正
-- 版本  : v0.3
-- 日期  : 2025-08-06
-- 说明  :
--   1. file_type 从 MIME 类型改为文件后缀（如 .pdf），无后缀时 NULL
--   2. is_chunked / is_vectorized 从 BOOLEAN 改为 SMALLINT 状态字段
--      状态：-1=失败, 0=未完成, 1=已完成, 2=进行中
-- 回滚  :
--   ALTER TABLE documents ALTER COLUMN file_type SET NOT NULL;
--   ALTER TABLE documents ALTER COLUMN is_chunked TYPE BOOLEAN USING (is_chunked = 1);
--   ALTER TABLE documents ALTER COLUMN is_vectorized TYPE BOOLEAN USING (is_vectorized = 1);
-- ============================================================

-- 1. file_type 改为可空 + 存后缀而非 MIME
ALTER TABLE documents ALTER COLUMN file_type DROP NOT NULL;
ALTER TABLE documents ALTER COLUMN file_type TYPE VARCHAR(100);

COMMENT ON COLUMN documents.file_type IS '文件后缀，如 .pdf，无后缀则为 NULL';

-- 2. is_chunked / is_vectorized：字段不存在则创建，存在则 BOOLEAN→SMALLINT
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_chunked    SMALLINT NOT NULL DEFAULT 0;
ALTER TABLE documents ADD COLUMN IF NOT EXISTS is_vectorized SMALLINT NOT NULL DEFAULT 0;

-- 兼容 001 已创建 BOOLEAN 的情况，统一转 SMALLINT（已是 SMALLINT 则 no-op）
ALTER TABLE documents
    ALTER COLUMN is_chunked    TYPE SMALLINT USING is_chunked::int,
    ALTER COLUMN is_chunked    SET DEFAULT 0,
    ALTER COLUMN is_vectorized TYPE SMALLINT USING is_vectorized::int,
    ALTER COLUMN is_vectorized SET DEFAULT 0;

COMMENT ON COLUMN documents.is_chunked    IS '切片状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON COLUMN documents.is_vectorized IS '向量化状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
