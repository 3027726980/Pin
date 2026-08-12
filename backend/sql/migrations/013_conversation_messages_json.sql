-- 013: 消息存储改版 —— messages 表 → conversations.messages JSONB（每会话一条记录）
--
-- 背景：
--   messages 表每条消息一行，行数 = 消息数；改为会话级 JSON 数组后行数 = 会话数。
--   写入用 SQL 原子追加（|| 拼接，数据库内部读-拼-写，无应用层读改写竞态）。
--   每轮对话（user + assistant + citations）作为一条 JSON 记录一次原子追加。
--
-- 注意：
--   1. 本迁移不可逆（旧 messages 表删除前数据已聚合进 conversations.messages）
--   2. 已软删除会话(status=9)的历史消息一并聚合（不会被读取，保持完整）

-- 1. conversations 表新增 messages 列
ALTER TABLE conversations
  ADD COLUMN IF NOT EXISTS messages JSONB NOT NULL DEFAULT '[]'::jsonb;

COMMENT ON COLUMN conversations.messages IS
  '会话消息 JSONB 数组：[{role, content, citations, created_at}]，按插入序；写入用 || 原子追加';

-- 2. 存量数据聚合：旧 messages 表 → conversations.messages
UPDATE conversations c
SET messages = COALESCE((
    SELECT jsonb_agg(jsonb_build_object(
        'role',       m.role,
        'content',    m.content,
        'citations',  m.citations,
        'created_at', m.created_at
    ) ORDER BY m.created_at)
    FROM messages m
    WHERE m.conversation_id = c.id AND m.status != 9
), '[]'::jsonb);

-- 3. 删除旧 messages 表（数据已聚合，单数据源）
DROP TABLE IF EXISTS messages;
