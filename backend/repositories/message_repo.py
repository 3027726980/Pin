"""消息数据访问 —— conversations.messages JSONB（每会话一条记录）

写入规范：一律用 SQL 原子追加（|| 拼接），数据库内部完成读-拼-写，
无应用层读改写竞态（并发 UPDATE 由行锁串行化，消息不丢失）。
禁止：SELECT 读回 → 内存修改 → 整体 UPDATE（会丢失并发写入）。
"""
import json
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class MessageRepo:
    """conversations.messages JSONB 操作（替代原 messages 表 CRUD）"""

    @staticmethod
    async def append_messages(db: AsyncSession, conversation_id: UUID,
                              msgs: list[dict]) -> None:
        """原子追加消息（单条 UPDATE，数据库内部拼接）

        COALESCE 处理首条消息（messages 为 '[]' 时拼接结果正确）；
        同一轮 user + assistant 一次追加，保证成对出现、顺序正确。
        """
        await db.execute(
            text("""
                UPDATE conversations
                SET messages = COALESCE(messages, '[]'::jsonb) || CAST(:msgs AS jsonb)
                WHERE id = :cid AND status != 9
            """),
            {"msgs": json.dumps(msgs, ensure_ascii=False),
             "cid": str(conversation_id)},
        )

    @staticmethod
    async def count(db: AsyncSession, conversation_id: UUID) -> int:
        """消息条数（jsonb_array_length，替代原 count 查询）"""
        n = await db.execute(
            text("""
                SELECT COALESCE(jsonb_array_length(messages), 0)
                FROM conversations WHERE id = :cid
            """),
            {"cid": str(conversation_id)},
        )
        return n.scalar() or 0

    @staticmethod
    async def list_by_conversation(db: AsyncSession, conversation_id: UUID,
                                   page: int = 1, page_size: int = 20
                                   ) -> tuple[list[dict], int]:
        """按会话分页读取（jsonb 数组切片，按插入序；空会话返回 [], 0）"""
        total = await MessageRepo.count(db, conversation_id)
        offset = (page - 1) * page_size
        rows = await db.execute(
            text("""
                SELECT jsonb_agg(t.m) FROM (
                    SELECT m FROM jsonb_array_elements(
                        (SELECT messages FROM conversations WHERE id = :cid)
                    ) WITH ORDINALITY AS t(m, ord)
                    ORDER BY t.ord LIMIT :lim OFFSET :off
                ) t
            """),
            {"cid": str(conversation_id), "lim": page_size, "off": offset},
        )
        return rows.scalar() or [], total

    @staticmethod
    async def first_user_message(db: AsyncSession,
                                 conversation_id: UUID) -> dict | None:
        """取会话首条 user 消息（JSON 数组第一条 role=user 的记录）"""
        row = await db.execute(
            text("""
                SELECT m FROM conversations c,
                     jsonb_array_elements(c.messages) WITH ORDINALITY AS t(m, ord)
                WHERE c.id = :cid AND m->>'role' = 'user'
                ORDER BY t.ord LIMIT 1
            """),
            {"cid": str(conversation_id)},
        )
        return row.scalar_one_or_none()
