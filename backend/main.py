"""
Pin 后端入口

Phase 1：FastAPI 启动 → 建表 → 种子管理员 → 注册认证路由
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from backend.core.database import async_session_local, init_db
from backend.core.security import hash_password
from backend.core.config import settings
from backend.models import User
from backend.repositories import UserRepo
from backend.api.v1 import auth_router, knowledge_router, model_config_router


# ── 种子管理员 ──────────────────────────────────────
async def seed_admin() -> None:
    """确保管理员账号存在（首次启动自动创建）"""
    async with async_session_local() as session:
        if await UserRepo.get_by_username(session, settings.admin.username) is None:
            admin = User(
                username=settings.admin.username,
                hashed_password=hash_password(settings.admin.password),
                is_superuser=True,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            print(f"[INIT] 管理员账号已创建: {settings.admin.username}")


# ── 生命周期 ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_admin()
    yield


# ── 应用实例 ────────────────────────────────────────
app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    lifespan=lifespan,
)

# ── 异常处理：统一响应格式 ──────────────────────────
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    """把 FastAPI 默认的 {detail: ...} 转成 {code, message, result}"""
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "code": exc.status_code,
            "message": exc.detail,
            "result": None,
        },
    )


# ── 注册路由 ────────────────────────────────────────
app.include_router(auth_router)
app.include_router(knowledge_router)
app.include_router(model_config_router)
