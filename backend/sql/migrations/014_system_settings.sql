-- 014: 通用系统设置表（JSON 配置存储；脱敏规则等系统级配置的唯一事实来源）
CREATE TABLE IF NOT EXISTS system_settings (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key         VARCHAR(100) NOT NULL UNIQUE,
    value       JSONB NOT NULL,
    description VARCHAR(200),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
COMMENT ON TABLE system_settings IS '通用系统设置表（JSON 配置存储）';
COMMENT ON COLUMN system_settings.key IS '设置项标识（如 logging.redact_rules）';
COMMENT ON COLUMN system_settings.value IS '配置值（任意 JSON 结构，后端自行解析）';
