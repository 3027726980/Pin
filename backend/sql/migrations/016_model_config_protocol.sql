-- Phase 4.7 补充：模型配置增加调用模式（协议）字段
-- 自定义厂商可显式声明调用模式（目前仅 openai）；空 = 按厂商推断默认 openai
-- 存量配置 protocol 为 NULL，行为不变（默认 openai）

ALTER TABLE user_model_config ADD COLUMN protocol VARCHAR(20);
