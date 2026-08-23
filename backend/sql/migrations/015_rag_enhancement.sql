-- Phase 4.6 RAG 检索增强：查询增强（MQE/HyDE）+ Rerank 配置字段
-- 1. simple_rag_agents：增强开关 + 子问题数 + rerank 开关（NOT NULL + DEFAULT，存量自动生效）
-- 2. 两张类型表：增强 LLM / Rerank 模型引用（FK ON DELETE SET NULL，与 summary_llm_config_id 一致）

ALTER TABLE simple_rag_agents
  ADD COLUMN mqe_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN hyde_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN mqe_query_count SMALLINT NOT NULL DEFAULT 3,
  ADD COLUMN rerank_enabled BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN enhance_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
  ADD COLUMN rerank_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL;

ALTER TABLE general_agents
  ADD COLUMN enhance_llm_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL,
  ADD COLUMN rerank_config_id UUID REFERENCES user_model_config(id) ON DELETE SET NULL;
