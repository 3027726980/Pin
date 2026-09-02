-- 021: documents 表新增 last_error（最近一次处理失败原因）
-- 上传自动处理（P3-10）：解析/分块/向量化失败时记录原因，前端展示，重新处理时清空
ALTER TABLE documents ADD COLUMN last_error TEXT NULL;

COMMENT ON COLUMN documents.last_error IS '最近一次处理失败原因（解析/分块/向量化），重新处理时清空';
