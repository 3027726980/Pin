-- ============================================================
-- 迁移 004: 拆分 chunks.is_vectorized，统一 status 语义
-- ============================================================
-- chunks.status: -1/0/1/2（向量化状态）→ 0=禁用, 1=启用, 9=软删除
-- chunks.is_vectorized: 新增字段，-1=失败, 0=未完成, 1=已完成, 2=进行中
-- embeddings.status: -1/0/1/2 → 0=禁用, 1=启用, 9=软删除

-- 1. chunks 新增 is_vectorized，从 status 迁移值
ALTER TABLE chunks ADD COLUMN IF NOT EXISTS is_vectorized SMALLINT NOT NULL DEFAULT 0;
-- 将旧的 status 值（-1/0/1/2）复制到 is_vectorized，已有向量记录的视为已完成
UPDATE chunks SET is_vectorized = CASE
    WHEN status IN (-1, 2) THEN status   -- 保留 -1=失败, 2=进行中
    WHEN status = 0 THEN 0               -- 未完成
    ELSE 0                               -- 其他默认未完成
END;
-- 有 embedding 记录的 chunk 标记为已完成
UPDATE chunks SET is_vectorized = 1
WHERE id IN (SELECT chunk_id FROM embeddings);

-- 2. chunks.status 重置为启用
UPDATE chunks SET status = 1 WHERE status NOT IN (0, 9);

-- 3. embeddings.status 重置为启用
UPDATE embeddings SET status = 1 WHERE status NOT IN (0, 9);

-- 4. 注释更新
COMMENT ON COLUMN chunks.status IS '0=禁用, 1=启用, 9=软删除';
COMMENT ON COLUMN chunks.is_vectorized IS '向量化状态：-1=失败, 0=未完成, 1=已完成, 2=进行中';
COMMENT ON COLUMN embeddings.status IS '0=禁用, 1=启用, 9=软删除（与关联 chunk 状态同步）';
