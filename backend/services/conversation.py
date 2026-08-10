"""会话业务:创建/列表/删除(软删 + 清理 checkpoint)"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import ConversationRepo, MessageRepo
from backend.schemas.conversation import ConversationResponse

# 会话默认标题(首轮对话后自动用首条用户消息命名)
DEFAULT_CONV_TITLE = "新会话"
from backend.repositories import AgentIndexRepo

class ConversationService:
    """会话业务逻辑"""

    @staticmethod
    async def create(db: AsyncSession, user: Users, agent_id: UUID,
                     title: str | None = None) -> ConversationResponse:
        """创建会话;未传标题时取该 Agent 最近会话首条用户消息前 20 字,无则'新会话'"""
        # 校验 Agent:存在 + 归属 + 未删除
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is None or entry.status == 9 or entry.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")

        if title is None:
            title = await ConversationService._auto_title(db, user, agent_id)
        conv = await ConversationRepo.create(
            db, user_id=user.id, agent_id=agent_id, title=title)
        await db.commit()
        await db.refresh(conv)
        return ConversationResponse(
            id=conv.id, agent_id=conv.agent_id, title=conv.title,
            message_count=0, created_at=conv.created_at,
            updated_at=conv.updated_at)

    @staticmethod
    async def _auto_title(db: AsyncSession, user: Users, agent_id: UUID) -> str:
        """取该 Agent 最近会话的首条用户消息前 20 字作为标题"""
        convs, _ = await ConversationRepo.list_by_user(
            db, user.id, page=1, page_size=1, agent_id=agent_id)
        if not convs:
            return DEFAULT_CONV_TITLE
        msg = await MessageRepo.first_user_message(db, convs[0].id)
        if msg is None:
            return DEFAULT_CONV_TITLE
        return msg.content[:20]

    @staticmethod
    async def list_by_user(db: AsyncSession, user: Users,
                           agent_id: UUID | None, page: int,
                           page_size: int) -> tuple[list[dict], int]:
        """会话列表(补消息数)"""
        items, total = await ConversationRepo.list_by_user(
            db, user.id, page, page_size, agent_id)
        result = []
        for conv in items:
            _, mcount = await MessageRepo.list_by_conversation(
                db, conv.id, page=1, page_size=1)
            result.append(ConversationResponse(
                id=conv.id, agent_id=conv.agent_id, title=conv.title,
                message_count=mcount, created_at=conv.created_at,
                updated_at=conv.updated_at))
        return result, total

    @staticmethod
    async def get_messages(db: AsyncSession, user: Users, conv_id: UUID,
                           page: int, page_size: int) -> tuple[list, int]:
        """历史消息(校验归属)"""
        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9 or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        msgs, total = await MessageRepo.list_by_conversation(
            db, conv_id, page, page_size)
        return msgs, total

    @staticmethod
    async def delete(db: AsyncSession, user: Users, conv_id: UUID) -> None:
        """删除会话:软删 + 消息软删 + checkpoint 数据清理"""
        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9 or conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        await ConversationRepo.soft_delete(db, conv)
        await ConversationRepo.soft_delete_messages(db, conv_id)
        await db.commit()

        # checkpoint 数据清理(独立连接)
        from backend.core.checkpointer import get_checkpointer

        cp = await get_checkpointer()
        await cp.adelete_thread(str(conv_id))
