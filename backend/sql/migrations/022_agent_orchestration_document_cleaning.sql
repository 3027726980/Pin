-- 022: 为文档清洗预览和图式 Agent 编排预留的知识库/文档清洗字段。
-- 清洗规则属于知识库；原始解析内容与清洗内容分开保存，避免规则变更覆盖原文。

ALTER TABLE knowledge_bases
    ADD COLUMN IF NOT EXISTS cleaning_config JSONB NOT NULL DEFAULT '{"rules": []}'::jsonb;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS cleaned_content TEXT NULL,
    ADD COLUMN IF NOT EXISTS is_cleaned SMALLINT NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS cleaning_config_hash VARCHAR(64) NULL;

COMMENT ON COLUMN knowledge_bases.cleaning_config IS '文档文本清洗规则（受限 JSON 配置）';
COMMENT ON COLUMN documents.cleaned_content IS '按知识库清洗规则处理后的完整纯文本';
COMMENT ON COLUMN documents.is_cleaned IS '清洗状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON COLUMN documents.cleaning_config_hash IS '生成 cleaned_content 所用清洗规则的 SHA-256';
