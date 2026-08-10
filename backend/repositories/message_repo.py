"""消息数据访问 —— 只写 SQL,不管业务规则"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Messages


class MessageRepo:
    """messages 表 CRUD"""

    @staticmethod
    async def create(db: AsyncSession, conversation_id: UUID, role: str,
                     content: str, citations: list | None) -> Messages:
        """创建消息(flush 不 commit)"""
        msg = Messages(conversation_id=conversation_id, role=role,
                       content=content, citations=citations)
        db.add(msg)
        await db.flush()
        return msg

    @staticmethod
    async def list_by_conversation(db: AsyncSession, conversation_id: UUID,
                                   page: int = 1, page_size: int = 20
                                   ) -> tuple[list[Messages], int]:
        """按会话分页(过滤 status=9,按创建时间正序)"""
        cond = [Messages.conversation_id == conversation_id,
                Messages.status != 9]
        total = (await db.execute(
            select(func.count()).where(*cond))).scalar() or 0
        q = (select(Messages).where(*cond)
             .order_by(Messages.created_at.asc())
             .offset((page - 1) * page_size).limit(page_size))
        items = (await db.execute(q)).scalars().all()
        return list(items), total
