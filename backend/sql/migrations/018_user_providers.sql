-- Phase 4.9：用户自定义厂商表（厂商实体化）
-- 与预置 model_providers 分离（seed 清空逻辑不误删用户数据）
-- 效果等同 config.yaml 预置：带 protocol，可挂模型（user_model_config.provider 引用名称）

CREATE TABLE IF NOT EXISTS user_providers (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    name        VARCHAR(50) NOT NULL,
    protocol    VARCHAR(20) NOT NULL DEFAULT 'openai',
    description VARCHAR(200),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_user_providers_name UNIQUE (user_id, name)
);

COMMENT ON TABLE user_providers IS '用户自定义厂商表：前端可增删改，效果等同 config.yaml 预置厂商（带调用模式 protocol）';
COMMENT ON COLUMN user_providers.user_id IS '所属用户 ID';
COMMENT ON COLUMN user_providers.name IS '厂商名（同用户下唯一）';
COMMENT ON COLUMN user_providers.protocol IS '调用模式（协议）：openai 等';
COMMENT ON COLUMN user_providers.description IS '备注说明';
