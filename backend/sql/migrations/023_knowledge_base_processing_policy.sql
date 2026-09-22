-- 023: 上传自动处理改为知识库级策略；系统设置仅保留新建知识库默认值。

ALTER TABLE knowledge_bases
    ADD COLUMN IF NOT EXISTS auto_process BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN knowledge_bases.auto_process
    IS '上传后是否自动执行到向量化；新建时复制系统默认值';
