-- Phase 4.12: RAG 增强三态模式（兼容期保留旧布尔字段）
ALTER TABLE simple_rag_agents
    ADD COLUMN IF NOT EXISTS mqe_mode VARCHAR(10),
    ADD COLUMN IF NOT EXISTS hyde_mode VARCHAR(10),
    ADD COLUMN IF NOT EXISTS rerank_mode VARCHAR(10);

UPDATE simple_rag_agents SET
    mqe_mode = CASE WHEN mqe_enabled THEN 'always' ELSE 'off' END,
    hyde_mode = CASE WHEN hyde_enabled THEN 'always' ELSE 'off' END,
    rerank_mode = CASE WHEN rerank_enabled THEN 'always' ELSE 'off' END
WHERE mqe_mode IS NULL OR hyde_mode IS NULL OR rerank_mode IS NULL;

ALTER TABLE simple_rag_agents
    ALTER COLUMN mqe_mode SET DEFAULT 'auto',
    ALTER COLUMN mqe_mode SET NOT NULL,
    ALTER COLUMN hyde_mode SET DEFAULT 'auto',
    ALTER COLUMN hyde_mode SET NOT NULL,
    ALTER COLUMN rerank_mode SET DEFAULT 'auto',
    ALTER COLUMN rerank_mode SET NOT NULL,
    ADD CONSTRAINT ck_simple_rag_agents_mqe_mode CHECK (mqe_mode IN ('off', 'auto', 'always')),
    ADD CONSTRAINT ck_simple_rag_agents_hyde_mode CHECK (hyde_mode IN ('off', 'auto', 'always')),
    ADD CONSTRAINT ck_simple_rag_agents_rerank_mode CHECK (rerank_mode IN ('off', 'auto', 'always'));

-- General Agent 的实际策略仍随每个 rag tool 保存；表级默认用于未来统一治理。
ALTER TABLE general_agents
    ADD COLUMN IF NOT EXISTS mqe_mode VARCHAR(10) NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS hyde_mode VARCHAR(10) NOT NULL DEFAULT 'auto',
    ADD COLUMN IF NOT EXISTS rerank_mode VARCHAR(10) NOT NULL DEFAULT 'auto',
    ADD CONSTRAINT ck_general_agents_mqe_mode CHECK (mqe_mode IN ('off', 'auto', 'always')),
    ADD CONSTRAINT ck_general_agents_hyde_mode CHECK (hyde_mode IN ('off', 'auto', 'always')),
    ADD CONSTRAINT ck_general_agents_rerank_mode CHECK (rerank_mode IN ('off', 'auto', 'always'));
