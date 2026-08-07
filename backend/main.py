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
from backend.models import Users, ModelProviders, ModelTypes, DefaultModelConfig
from backend.repositories import UserRepo
from backend.api.v1 import auth_router, knowledge_router, user_model_config_router


# ── 种子管理员 ──────────────────────────────────────
async def seed_admin() -> None:
    """确保管理员账号存在（首次启动自动创建）"""
    async with async_session_local() as session:
        if await UserRepo.get_by_username(session, settings.admin.username) is None:
            admin = Users(
                username=settings.admin.username,
                hashed_password=hash_password(settings.admin.password),
                is_superuser=True,
                is_active=True,
            )
            session.add(admin)
            await session.commit()
            print(f"[INIT] 管理员账号已创建: {settings.admin.username}")


# ── 种子模型配置 ─────────────────────────────────
# 每次启动时：清空 model_providers + default_model_config，再从 config.yaml 重新插入。
# 避免 config.yaml 删除厂商/模型后数据库残留旧数据。
# user_model_config 不受影响（仅存 provider 字符串，无 FK 依赖）。
async def seed_model_config() -> None:
    async with async_session_local() as session:
        from sqlalchemy import delete

        providers = getattr(settings, "model_providers", None)
        if providers is None:
            return

        # 1. 清空旧数据
        await session.execute(delete(DefaultModelConfig))
        await session.execute(delete(ModelProviders))
        await session.execute(delete(ModelTypes))

        # 2. 插入模型类型对照
        model_types = getattr(settings, "model_types", [])
        if isinstance(model_types, list):
            for mt in model_types:
                session.add(ModelTypes(code=mt["code"], name=mt["name"]))
                print(f"[INIT] 模型类型已创建: {mt['code']} → {mt['name']}")

        # 3. 插入厂商和默认模型
        for provider_name, provider_cfg in vars(providers).items():
            session.add(ModelProviders(name=provider_name))
            print(f"[INIT] 厂商已创建: {provider_name}")

            models = getattr(provider_cfg, "models", [])
            if isinstance(models, list):
                for m in models:
                    session.add(DefaultModelConfig(
                        provider=provider_name,
                        model_name=m["model_name"],
                        model_type=m["model_type"],
                        base_url=m["base_url"],
                        dimension=m.get("dimension"),
                    ))
                    print(f"[INIT] 默认模型已创建: {provider_name}/{m['model_name']} (dim={m.get('dimension')})")

        await session.commit()


# ── 生命周期 ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_admin()
    await seed_model_config()
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
app.include_router(user_model_config_router)
