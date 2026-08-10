"""会话数据访问 —— 只写 SQL,不管业务规则"""
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Conversations, Messages


class ConversationRepo:
    """conversations 表 CRUD"""

    @staticmethod
    async def create(db: AsyncSession, user_id: UUID, agent_id: UUID,
                     title: str | None) -> Conversations:
        """创建会话(flush 不 commit)"""
        conv = Conversations(user_id=user_id, agent_id=agent_id, title=title)
        db.add(conv)
        await db.flush()
        return conv

    @staticmethod
    async def get_by_id(db: AsyncSession, conv_id: UUID) -> Conversations | None:
        """按主键查询(不做状态过滤)"""
        return await db.get(Conversations, conv_id)

    @staticmethod
    async def list_by_user(db: AsyncSession, user_id: UUID, page: int = 1,
                           page_size: int = 20,
                           agent_id: UUID | None = None
                           ) -> tuple[list[Conversations], int]:
        """按用户分页(过滤 status=9,可按 agent 过滤,按创建时间倒序)"""
        cond = [Conversations.user_id == user_id, Conversations.status != 9]
        if agent_id:
            cond.append(Conversations.agent_id == agent_id)
        total = (await db.execute(
            select(func.count()).where(*cond))).scalar() or 0
        q = (select(Conversations).where(*cond)
             .order_by(Conversations.created_at.desc())
             .offset((page - 1) * page_size).limit(page_size))
        items = (await db.execute(q)).scalars().all()
        return list(items), total

    @staticmethod
    async def soft_delete(db: AsyncSession, conv: Conversations) -> None:
        """软删除(status → 9)"""
        conv.status = 9
        await db.flush()

    @staticmethod
    async def update_title(db: AsyncSession, conv: Conversations,
                           title: str) -> None:
        """更新会话标题(首轮对话自动命名用)"""
        conv.title = title
        await db.flush()

    @staticmethod
    async def soft_delete_messages(db: AsyncSession, conv_id: UUID) -> int:
        """软删除会话下全部消息,返回行数"""
        from sqlalchemy import update as _update

        result = await db.execute(
            _update(Messages)
            .where(Messages.conversation_id == conv_id, Messages.status != 9)
            .values(status=9))
        await db.flush()
        return result.rowcount
