-- 024: 文件级处理策略与当前生效切片的策略版本。

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS processing_config JSONB NULL;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS applied_processing_config_hash VARCHAR(64) NULL;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS applied_algorithm_version INTEGER NULL;

COMMENT ON COLUMN documents.processing_config
    IS '文件独立处理策略；NULL 表示继承知识库默认策略';
COMMENT ON COLUMN documents.applied_processing_config_hash
    IS '当前生效切片所用完整处理策略的 SHA-256';
COMMENT ON COLUMN documents.applied_algorithm_version
    IS '当前生效切片所用处理算法版本';
