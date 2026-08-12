"""
Pin 后端入口

Phase 1：FastAPI 启动 → 建表 → 种子管理员 → 注册认证路由
"""

# Windows:psycopg async 不支持 ProactorEventLoop,需切换 SelectorEventLoop
# (必须在使用事件循环前设置,uvicorn 导入本模块时生效)
import asyncio
import logging
import sys

if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

# 屏蔽 pydub 的 ffmpeg 缺失警告（markitdown 音频转录转换器触发，本项目不使用音频解析）
import warnings

warnings.filterwarnings(
    "ignore",
    message="Couldn't find ffmpeg or avconv.*",
    category=RuntimeWarning,
)

from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from backend.core.database import async_session_local, init_db
from backend.core.security import hash_password
from backend.core.config import settings
from backend.core.checkpointer import get_checkpointer
from backend.models import Users, ModelProviders, ModelTypes, DefaultModelConfig
from backend.repositories import UserRepo
from backend.api.v1 import (
    agent_api_key_router,
    agent_router,
    debug_router,
    auth_router,
    conversation_router,
    knowledge_router,
    public_router,
    settings_router,
    user_model_config_router,
)


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
# 按 config.yaml 与数据库差异比对后同步（无变化不动库）：
# 缺的插入、多的删除、变化的更新。避免每次启动全量 DELETE+INSERT
# （启动中途失败会清空配置表的风险），也减少启动写操作。
# user_model_config 不受影响（仅存 provider 字符串，无 FK 依赖）。
async def seed_model_config() -> None:
    async with async_session_local() as session:
        from sqlalchemy import select

        providers = getattr(settings, "model_providers", None)
        if providers is None:
            return

        # 期望状态（config.yaml）
        expect_types = {mt["code"]: mt["name"]
                        for mt in getattr(settings, "model_types", []) or []}
        expect_providers = set(vars(providers).keys())
        expect_models: dict = {}
        for pname, pcfg in vars(providers).items():
            for m in getattr(pcfg, "models", []) or []:
                expect_models[(pname, m["model_name"])] = {
                    "model_type": m["model_type"],
                    "base_url": m["base_url"],
                    "dimension": m.get("dimension"),
                }

        # 数据库现状
        db_types = {t.code: t for t in
                    (await session.execute(select(ModelTypes))).scalars()}
        db_providers = {p.name: p for p in
                        (await session.execute(select(ModelProviders))).scalars()}
        db_models = {(d.provider, d.model_name): d for d in
                     (await session.execute(select(DefaultModelConfig))).scalars()}

        changed = False
        # 模型类型 diff
        for code, name in expect_types.items():
            t = db_types.get(code)
            if t is None:
                session.add(ModelTypes(code=code, name=name))
                changed = True
            elif t.name != name:
                t.name = name
                changed = True
        for code in set(db_types) - set(expect_types):
            await session.delete(db_types[code])
            changed = True
        # 厂商 diff
        for p in expect_providers:
            if p not in db_providers:
                session.add(ModelProviders(name=p))
                changed = True
        for p in set(db_providers) - expect_providers:
            await session.delete(db_providers[p])
            changed = True
        # 默认模型 diff
        for key, exp in expect_models.items():
            d = db_models.get(key)
            if d is None:
                session.add(DefaultModelConfig(provider=key[0], model_name=key[1], **exp))
                changed = True
            elif (d.model_type != exp["model_type"]
                  or d.base_url != exp["base_url"]
                  or d.dimension != exp["dimension"]):
                d.model_type, d.base_url, d.dimension = \
                    exp["model_type"], exp["base_url"], exp["dimension"]
                changed = True
        for key in set(db_models) - set(expect_models):
            await session.delete(db_models[key])
            changed = True

        if changed:
            await session.commit()
            print("[INIT] 模型配置已按 config.yaml 同步（差异更新）")
        else:
            await session.rollback()
            print("[INIT] 模型配置与 config.yaml 一致，跳过")

        await session.commit()


# ── 生命周期 ────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    await seed_admin()
    await seed_model_config()
    await get_checkpointer()   # 初始化 checkpoint 表(幂等)

    # 日志体系初始化 + 系统设置（seed + 缓存 + 脱敏 Filter 挂载）
    from backend.core.logging_setup import (
        RedactFilter, setup_logging, start_cleanup_task,
    )
    from backend.services.system_settings import SystemSettingsService

    setup_logging()
    async with async_session_local() as session:
        await SystemSettingsService.init(session)
    global _redact_filter
    _redact_filter = RedactFilter(SystemSettingsService.get("logging.redact_rules"))
    # 挂载到全部 handler（root + 分文件 handler：llm/http/sql 同样脱敏）
    for _lgr_name in ("", "backend.llm", "backend.http", "sqlalchemy.engine"):
        for _h in logging.getLogger(_lgr_name).handlers:
            _h.addFilter(_redact_filter)
    SystemSettingsService.register_on_change(_on_setting_change)
    _cleanup_task = await start_cleanup_task()
    try:
        yield
    finally:
        _cleanup_task.cancel()


# ── 应用实例 ────────────────────────────────────────
app = FastAPI(
    title=settings.app.name,
    version=settings.app.version,
    lifespan=lifespan,
)

# ── 日志体系：脱敏 Filter 全局引用 + 设置变更回调 ──────────
_redact_filter = None


async def _on_setting_change(key: str, value: dict) -> None:
    """系统设置变更回调：脱敏规则更新 → 重建 Filter（立即生效）"""
    if key == "logging.redact_rules" and _redact_filter is not None:
        _redact_filter.reload(value)
        logging.getLogger("backend").info("脱敏规则已更新并生效")


# ── HTTP 访问日志中间件（backend.http → http.log）──────────
import time as _time

_http_logger = logging.getLogger("backend.http")


class HttpAccessLogMiddleware:
    """纯 ASGI 中间件：记录每个请求的 方法/路径/状态/耗时/IP + 请求体 + 响应体（脱敏 Filter 兜底）

    用纯 ASGI 而非 BaseHTTPMiddleware 的原因：
      - 需要收集**响应体**（含 SSE 流式响应）——BaseHTTPMiddleware 拿不到发送中的 body
      - 包装 receive/send：请求体在读取时收集，响应体在发送时收集（SSE 也在流结束后完整记录）
    """

    # 请求/响应体收集上限（config.yaml logging.http_body_max_bytes，0 = 不收集）
    def __init__(self, app):
        self.app = app
        try:
            self.max_collect = int(
                getattr(settings.logging, "http_body_max_bytes", 1024 * 1024))
        except (AttributeError, ValueError, TypeError):
            self.max_collect = 1024 * 1024

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        start = _time.perf_counter()
        req_chunks: list[bytes] = []
        resp_chunks: list[bytes] = []
        status = 0

        async def receive_wrapper():
            message = await receive()
            if message["type"] == "http.request":
                body = message.get("body", b"")
                if len(b"".join(req_chunks)) < self.max_collect:
                    req_chunks.append(body)
            return message

        async def send_wrapper(message):
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
            elif message["type"] == "http.response.body":
                body = message.get("body", b"")
                if len(b"".join(resp_chunks)) < self.max_collect:
                    resp_chunks.append(body)
            await send(message)

        await self.app(scope, receive_wrapper, send_wrapper)

        duration_ms = int((_time.perf_counter() - start) * 1000)
        # 完整记录请求/响应体；换行转义为 \n 保持单行（便于 grep/日志解析）
        req_text = b"".join(req_chunks).decode("utf-8", errors="replace")
        resp_text = b"".join(resp_chunks).decode("utf-8", errors="replace")
        req_preview = req_text.replace("\r", "\\r").replace("\n", "\\n")
        resp_preview = resp_text.replace("\r", "\\r").replace("\n", "\\n")
        _http_logger.info(
            "method=%s path=%s status=%d duration_ms=%d ip=%s authorization=%s body=%s response=%s",
            scope.get("method", ""), scope.get("path", ""), status, duration_ms,
            scope.get("client", ("unknown", 0))[0],
            dict(scope.get("headers", []))
            .get(b"authorization", b"").decode("utf-8", errors="replace"),
            req_preview, resp_preview,
        )


# 注册 HTTP 访问日志中间件（在 public_cors 之后添加 = 更外层，先收集请求体）
app.add_middleware(HttpAccessLogMiddleware)


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
app.include_router(agent_router)
app.include_router(auth_router)
app.include_router(conversation_router)
app.include_router(knowledge_router)
app.include_router(user_model_config_router)
app.include_router(agent_api_key_router)
app.include_router(debug_router)
app.include_router(public_router)
app.include_router(settings_router)

# ── 公开接口 CORS（仅 /api/v1/public/ 放开，主站保持同源）──────
@app.middleware("http")
async def public_cors_middleware(request: Request, call_next):
    """公开接口跨域支持：动态回显 Origin；域名白名单由 deps_public 校验"""
    if not request.url.path.startswith("/api/v1/public/"):
        return await call_next(request)
    origin = request.headers.get("origin")
    # 预检请求直接放行
    if request.method == "OPTIONS":
        resp = JSONResponse(status_code=200, content={"code": 200, "message": "ok", "result": None})
    else:
        resp = await call_next(request)
    if origin:
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, PUT, DELETE, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Authorization, Content-Type, X-API-Key"
        resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


# ── widget 静态托管 + 全屏聊天页 ───────────────────────
import os

_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_WIDGET_DIR = os.path.join(_STATIC_DIR, "widget")
os.makedirs(_WIDGET_DIR, exist_ok=True)
app.mount("/widget", StaticFiles(directory=_WIDGET_DIR), name="widget")


@app.get("/chat/embed/{agent_id}", response_class=HTMLResponse,
         summary="全屏聊天页（iframe 嵌入用）")
async def chat_embed(agent_id: str, api_key: str = ""):
    """全屏模式独立页面：宿主 iframe 直接嵌入

    用法: <iframe src="https://host/chat/embed/{agent_id}?api_key=xxx">
    """
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>智能助手</title>
  <style>
    html, body {{ margin: 0; padding: 0; height: 100%; overflow: hidden; background: #fff; }}
  </style>
</head>
<body>
  <div id="pin-widget-root"></div>
  <script src="/widget/widget.js"></script>
  <script>
    window.PinWidget.init({{
      agentId: {agent_id!r},
      apiKey: {api_key!r},
      mode: 'fullscreen',
      root: '#pin-widget-root',
    }});
  </script>
</body>
</html>""")
