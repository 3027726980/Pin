"""会话数据访问 —— 只写 SQL,不管业务规则"""
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy import delete, func, select, update as _update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Conversations, Messages


class ConversationRepo:
    """conversations 表 CRUD"""

    @staticmethod
    async def create(db: AsyncSession, user_id: UUID | None, agent_id: UUID,
                     title: str | None,
                     client_id: str | None = None) -> Conversations:
        """创建会话(flush 不 commit)；匿名场景 user_id 传 None + client_id"""
        conv = Conversations(user_id=user_id, agent_id=agent_id,
                             title=title, client_id=client_id)
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
    async def list_by_client(db: AsyncSession, client_id: str, page: int = 1,
                             page_size: int = 20,
                             agent_id: UUID | None = None
                             ) -> tuple[list[Conversations], int]:
        """按匿名访客标识分页(过滤 status=9,可按 agent 过滤,按创建时间倒序)"""
        cond = [Conversations.client_id == client_id, Conversations.status != 9]
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
    async def purge_stale_anonymous(db: AsyncSession, agent_id: UUID,
                                    retention_days: int) -> int:
        """惰性清理:软删指定 Agent 下超过保留天数无活动的匿名会话,返回清理数"""
        cutoff = datetime.now() - timedelta(days=retention_days)
        result = await db.execute(
            _update(Conversations)
            .where(
                Conversations.agent_id == agent_id,
                Conversations.client_id.isnot(None),
                Conversations.status != 9,
                Conversations.updated_at < cutoff,
            )
            .values(status=9))
        await db.flush()
        return result.rowcount

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
