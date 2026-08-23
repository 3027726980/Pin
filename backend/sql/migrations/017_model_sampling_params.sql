-- Phase 4.8：模型配置支持采样参数（temperature/top_p/max_tokens）
-- 1. user_model_config 加采样参数（可空 = 未配置，Agent 未单独设置时生效）
-- 2. Agent 采样参数改可空（空 = 跟随模型配置）；新增 max_tokens

ALTER TABLE user_model_config
  ADD COLUMN temperature DOUBLE PRECISION,
  ADD COLUMN top_p DOUBLE PRECISION,
  ADD COLUMN max_tokens INTEGER;

ALTER TABLE simple_rag_agents
  ALTER COLUMN temperature DROP DEFAULT,
  ALTER COLUMN temperature DROP NOT NULL,
  ALTER COLUMN top_p DROP DEFAULT,
  ALTER COLUMN top_p DROP NOT NULL,
  ADD COLUMN max_tokens INTEGER;

ALTER TABLE general_agents
  ALTER COLUMN temperature DROP DEFAULT,
  ALTER COLUMN temperature DROP NOT NULL,
  ALTER COLUMN top_p DROP DEFAULT,
  ALTER COLUMN top_p DROP NOT NULL,
  ADD COLUMN max_tokens INTEGER;
