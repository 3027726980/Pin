-- 作者：LHF；时间：2026-10-25；作用：删除 simple_rag 及关联数据，保留 general。
-- 推荐使用 python -m backend.scripts.cleanup_simple_agents --apply，先导出并清理独立 checkpoint 库。
-- 本脚本在外部事务内执行；可重入。历史迁移保持不变。
CREATE TEMP TABLE pin_removed_agent_ids (id uuid PRIMARY KEY) ON COMMIT DROP;
INSERT INTO pin_removed_agent_ids SELECT id FROM agent_index WHERE type = 'simple_rag';
DO $$ BEGIN
    IF to_regclass('simple_rag_agents') IS NOT NULL THEN
        INSERT INTO pin_removed_agent_ids SELECT id FROM simple_rag_agents ON CONFLICT DO NOTHING;
    END IF;
END $$;
CREATE TEMP TABLE pin_removed_conversation_ids ON COMMIT DROP AS
SELECT id FROM conversations WHERE agent_id IN (SELECT id FROM pin_removed_agent_ids);
DO $$ DECLARE table_name text; BEGIN
    FOREACH table_name IN ARRAY ARRAY['checkpoint_writes', 'checkpoint_blobs', 'checkpoints'] LOOP
        IF to_regclass(table_name) IS NOT NULL THEN
            EXECUTE format('DELETE FROM %I WHERE thread_id IN (SELECT id::text FROM pin_removed_conversation_ids UNION ALL SELECT ''memory_v2:'' || id::text FROM pin_removed_conversation_ids)', table_name);
        END IF;
    END LOOP;
END $$;
DELETE FROM agent_api_keys WHERE agent_id IN (SELECT id FROM pin_removed_agent_ids);
DELETE FROM conversations WHERE id IN (SELECT id FROM pin_removed_conversation_ids);
DROP TABLE IF EXISTS simple_rag_agents;
DELETE FROM agent_index WHERE id IN (SELECT id FROM pin_removed_agent_ids);
UPDATE general_agents
SET intent_rules = jsonb_set(COALESCE(intent_rules, '{}'::jsonb), '{rules}',
    COALESCE((SELECT jsonb_agg(rule) FROM jsonb_array_elements(COALESCE(intent_rules->'rules', '[]'::jsonb)) AS rule
              WHERE rule->>'target' IS DISTINCT FROM 'simple'), '[]'::jsonb))
WHERE EXISTS (SELECT 1 FROM jsonb_array_elements(COALESCE(intent_rules->'rules', '[]'::jsonb)) AS rule
              WHERE rule->>'target' = 'simple');
