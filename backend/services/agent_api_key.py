"""Agent 嵌入密钥业务：生成（哈希存储）/ 列表 / 编辑 / 吊销"""
import hashlib
import secrets
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Users
from backend.repositories import AgentApiKeyRepo, AgentIndexRepo
from backend.schemas.agent_api_key import (
    AgentApiKeyCreated,
    AgentApiKeyResponse,
)

# Key 格式：pin_ + 32 位 URL-safe 随机串（224 bit 熵）
KEY_PREFIX = "pin_"
KEY_LENGTH = 32


def hash_api_key(api_key: str) -> str:
    """SHA-256 哈希（公开接口鉴权时用相同算法比对）"""
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


class AgentApiKeyService:
    """Agent 嵌入密钥业务逻辑"""

    @staticmethod
    async def _check_agent(db: AsyncSession, user: Users,
                           agent_id: UUID) -> object:
        """校验 Agent 存在 + 归属 + 未删除"""
        entry = await AgentIndexRepo.get_by_id(db, agent_id)
        if entry is None or entry.status == 9 or entry.user_id != user.id:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        return entry

    @staticmethod
    async def create(db: AsyncSession, user: Users, agent_id: UUID,
                     name: str | None = None) -> AgentApiKeyCreated:
        """生成密钥：明文只返回一次，服务端存哈希 + 前缀预览"""
        await AgentApiKeyService._check_agent(db, user, agent_id)
        plain = KEY_PREFIX + secrets.token_urlsafe(KEY_LENGTH)
        # 前缀预览：pin_ + 前 10 位，如 pin_AbC123xYzW...
        preview = plain[:14] + "..."
        key = await AgentApiKeyRepo.create(
            db, agent_id, hash_api_key(plain), preview, name)
        await db.commit()
        await db.refresh(key)
        resp = AgentApiKeyResponse.model_validate(key)
        return AgentApiKeyCreated(**resp.model_dump(), api_key=plain)

    @staticmethod
    async def list_by_agent(db: AsyncSession, user: Users,
                            agent_id: UUID) -> list[AgentApiKeyResponse]:
        """密钥列表（不含明文）"""
        await AgentApiKeyService._check_agent(db, user, agent_id)
        keys = await AgentApiKeyRepo.list_by_agent(db, agent_id)
        return [AgentApiKeyResponse.model_validate(k) for k in keys]

    @staticmethod
    async def update(db: AsyncSession, user: Users, agent_id: UUID,
                     key_id: UUID, name: str | None = None,
                     enabled: int | None = None) -> AgentApiKeyResponse:
        """编辑密钥（备注/启停）"""
        await AgentApiKeyService._check_agent(db, user, agent_id)
        key = await AgentApiKeyRepo.get_by_id(db, key_id)
        if key is None or key.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="密钥不存在")
        await AgentApiKeyRepo.update(db, key, name=name, enabled=enabled)
        await db.commit()
        await db.refresh(key)
        return AgentApiKeyResponse.model_validate(key)

    @staticmethod
    async def delete(db: AsyncSession, user: Users, agent_id: UUID,
                     key_id: UUID) -> None:
        """吊销密钥"""
        await AgentApiKeyService._check_agent(db, user, agent_id)
        key = await AgentApiKeyRepo.get_by_id(db, key_id)
        if key is None or key.agent_id != agent_id:
            raise HTTPException(status_code=404, detail="密钥不存在")
        await AgentApiKeyRepo.soft_delete(db, key)
        await db.commit()
