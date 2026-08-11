-- 012_agent_api_key_preview.sql
-- Phase 5.1: 嵌入密钥增加前缀预览（列表辨识用，非明文）
ALTER TABLE agent_api_keys
    ADD COLUMN IF NOT EXISTS key_preview VARCHAR(20);

-- 注释（幂等）
COMMENT ON COLUMN agent_api_keys.key_preview IS '明文前缀预览（如 pin_AbC123...，非明文，仅列表辨识用）';
