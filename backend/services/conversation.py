"""会话业务:创建/列表/删除(软删 + 清理 checkpoint)"""
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import ConversationRepo, MessageRepo, AgentIndexRepo
from backend.schemas.conversation import ConversationResponse

# 会话默认标题(首轮对话后自动用首条用户消息命名)
DEFAULT_CONV_TITLE = "新会话"

class ConversationService:
    """会话业务逻辑"""

    @staticmethod
    async def create(db: AsyncSession, user: Users, agent_id: UUID,
                     title: str | None = None,
                     client_id: str | None = None,
                     exec_user: Users | None = None) -> ConversationResponse:
        """创建会话;未传标题时使用默认标题'新会话',
        首轮对话后由 chat 服务用首条用户消息前 10 字自动命名

        匿名场景(client_id 非空):会话 user_id 存空 + client_id 标识访客;
        登录场景:user_id 归属用户。
        exec_user:公开接口登录场景的 Agent 所有者（用于归属校验，会话仍归 user）。
        """
        # 校验 Agent:存在 + 归属 + 未删除（exec_user 优先于 user 做归属校验）
        check_user = exec_user or user
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is None or entry.status == 9 or entry.user_id != check_user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")

        if title is None:
            title = DEFAULT_CONV_TITLE
        conv = await ConversationRepo.create(
            db, user_id=None if client_id else user.id,
            agent_id=agent_id, title=title, client_id=client_id)
        await db.commit()
        await db.refresh(conv)
        return ConversationResponse(
            id=conv.id, agent_id=conv.agent_id, title=conv.title,
            message_count=0, created_at=conv.created_at,
            updated_at=conv.updated_at)

    @staticmethod
    async def list_by_user(db: AsyncSession, user: Users,
                           agent_id: UUID | None, page: int,
                           page_size: int) -> tuple[list[dict], int]:
        """会话列表(补消息数)"""
        items, total = await ConversationRepo.list_by_user(
            db, user.id, page, page_size, agent_id)
        result = []
        for conv in items:
            mcount = await MessageRepo.count(db, conv.id)
            result.append(ConversationResponse(
                id=conv.id, agent_id=conv.agent_id, title=conv.title,
                message_count=mcount, created_at=conv.created_at,
                updated_at=conv.updated_at))
        return result, total

    @staticmethod
    async def list_by_client(db: AsyncSession, agent: object,
                             client_id: str, page: int,
                             page_size: int) -> tuple[list[dict], int]:
        """匿名访客会话列表(补消息数);先惰性清理超期匿名会话"""
        await ConversationRepo.purge_stale_anonymous(
            db, agent.id, agent.anonymous_retention_days)
        await db.commit()
        items, total = await ConversationRepo.list_by_client(
            db, client_id, page, page_size, agent.id)
        result = []
        for conv in items:
            mcount = await MessageRepo.count(db, conv.id)
            result.append(ConversationResponse(
                id=conv.id, agent_id=conv.agent_id, title=conv.title,
                message_count=mcount, created_at=conv.created_at,
                updated_at=conv.updated_at))
        return result, total

    @staticmethod
    async def get_messages(db: AsyncSession, user: Users, conv_id: UUID,
                           page: int, page_size: int,
                           client_id: str | None = None) -> tuple[list, int]:
        """历史消息(校验归属);匿名场景按 client_id 校验"""
        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9:
            raise HTTPException(status_code=404, detail="会话不存在")
        if client_id:
            if conv.client_id != client_id:
                raise HTTPException(status_code=404, detail="会话不存在")
        elif conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        msgs, total = await MessageRepo.list_by_conversation(
            db, conv_id, page, page_size)
        return msgs, total

    @staticmethod
    async def delete(db: AsyncSession, user: Users, conv_id: UUID,
                     client_id: str | None = None) -> None:
        """删除会话:软删 + 消息软删 + checkpoint 数据清理

        归属校验：匿名场景（client_id 非空）按 client_id；登录场景按 user_id
        （与 get_messages 一致，删不掉别人的会话）。
        """
        conv = await ConversationRepo.get_by_id(db, conv_id)
        if conv is None or conv.status == 9:
            raise HTTPException(status_code=404, detail="会话不存在")
        if client_id:
            if conv.client_id != client_id:
                raise HTTPException(status_code=404, detail="会话不存在")
        elif conv.user_id != user.id:
            raise HTTPException(status_code=404, detail="会话不存在")
        await ConversationRepo.soft_delete(db, conv)
        await ConversationRepo.clear_messages(db, conv_id)
        await db.commit()

        # checkpoint 数据清理(独立连接)
        from backend.core.checkpointer import get_checkpointer

        cp = await get_checkpointer()
        await cp.adelete_thread(str(conv_id))
