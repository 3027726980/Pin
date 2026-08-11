"""公开接口依赖：X-API-Key 鉴权 + 域名白名单 + 可选登录身份

设计要点：
- API Key 是 Agent 所有者的授权凭证（权限锁死在该 Agent 内）
- 通过鉴权后返回 (agent_index 记录, 所有者 Users)
- 访客身份：JWT 优先（登录态）；无 JWT 时用 client_id（匿名，由路由层读取）
"""
from urllib.parse import urlparse

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from backend.core.database import get_db
from backend.core.rate_limiter import check_rate_limit
from backend.core.security import decode_token
from backend.models import Users
from backend.repositories import (
    AgentApiKeyRepo,
    AgentIndexRepo,
    TokenWhitelistRepo,
    UserRepo,
)
from backend.services.agent_api_key import hash_api_key

_bearer = HTTPBearer(auto_error=False)


def _check_domain(agent: object, request: Request) -> None:
    """域名白名单校验：allowed_domains 为空 = 不限制"""
    domains = agent.allowed_domains or []
    if not domains:
        return
    origin = request.headers.get("origin") or request.headers.get("referer") or ""
    if not origin:
        # 无 Origin（curl 等非浏览器场景）不校验——白名单主要防浏览器跨域盗用
        return
    host = urlparse(origin).hostname or ""
    if host not in domains:
        raise HTTPException(status_code=403, detail="域名不在白名单内")


def get_public_agent(kind: str = "write"):
    """
    公开接口鉴权依赖工厂：X-API-Key（或 query api_key）→ 哈希比对 → 校验启用/Agent 存活
    → 域名白名单 → 按 kind 分级限流

    kind:
      - "write"：对话 / 创建会话等写操作，走 rate_limit_per_min 限流（与原来一致）
      - "read"：会话列表 / 历史消息等读操作，鉴权后不限流（浏览历史不受限流影响）

    鉴权三层（Key / 白名单 / 归属校验）两个 kind 完全一致——
    读操作只是不限流，不是免鉴权；Key 错误/白名单外/agent 禁用照样 401/403/404。

    注意：工厂本身必须是普通函数（非 async），返回内部 async 依赖；
    若为 async def 则调用后返回协程对象，FastAPI 无法解析（TypeError: not a callable）。

    返回 (agent_index, owner_user)；供后续接口复用，注入为依赖。
    """

    async def _dep(
        request: Request,
        db: AsyncSession = Depends(get_db),
    ):
        api_key = request.headers.get("X-API-Key") or request.query_params.get("api_key")
        if not api_key:
            raise HTTPException(status_code=401, detail="缺少 API Key")

        key = await AgentApiKeyRepo.get_by_hash(db, hash_api_key(api_key))
        if key is None or key.enabled != 1:
            raise HTTPException(status_code=401, detail="API Key 无效或已禁用")

        agent = await AgentIndexRepo.get_by_id(db, key.agent_id)
        if agent is None or agent.status == 9:
            raise HTTPException(status_code=404, detail="Agent 不存在")
        if agent.status == 0:
            raise HTTPException(status_code=400, detail="Agent 已禁用")

        _check_domain(agent, request)

        # 限流：仅写操作（对话/创建会话，防 LLM 成本被刷）；读操作鉴权后直接放行
        if kind == "write":
            client_ip = request.client.host if request.client else "unknown"
            if not check_rate_limit(f"{client_ip}:{str(agent.id)}",
                                    agent.rate_limit_per_min):
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

        owner = await UserRepo.get_by_id(db, agent.user_id)
        if owner is None or not owner.is_active:
            raise HTTPException(status_code=403, detail="Agent 所有者不可用")

        # 记录最后使用时间（尽力而为）
        await AgentApiKeyRepo.touch_used_at(db, key.id)
        await db.commit()

        return agent, owner

    return _dep


async def get_optional_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> Users | None:
    """
    可选登录：有合法 JWT 返回用户，否则返回 None（不抛 401）

    公开接口的访客身份：登录态 → user；匿名 → 由路由层读取 client_id。
    """
    if credentials is None:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        return None
    jti = payload.get("jti")
    if await TokenWhitelistRepo.find_valid_access(db, jti) is None:
        return None
    user = await UserRepo.get_by_id(db, payload.get("sub"))
    if user is None or not user.is_active:
        return None
    return user
