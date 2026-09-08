from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from backend.models import Base
from backend.core.config import settings

# 创建异步引擎
async_engine = create_async_engine(
    settings.database.url,                          # 数据库连接字符串
    echo=settings.database.echo,                    # 是否打印 SQL
    pool_size=settings.database.pool_size,          # 连接池大小
    max_overflow=settings.database.max_overflow,    # 连接池溢出大小
    pool_pre_ping=True,                             # 取连接时验证存活（防 PG 断开空闲连接后复用失效连接）
)

# 创建异步会话工厂
async_session_local = async_sessionmaker(
    bind=async_engine,      # 绑定引擎
    class_=AsyncSession,    # 使用异步会话
    expire_on_commit=False  # 设置会话不立即过期, 不hi重新查询数据库
)

# 依赖项
async def get_db():
    async with async_session_local() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

# 初始化
async def init_db():
    """建表初始化（幂等，应用启动与测试环境共用）

    顺序：先幂等创建 pgvector 扩展（容器/全新库首次启动必需，
    chunks.embedding 的 vector 类型依赖它；本地已建扩展时为 no-op），
    再 create_all 同步全部 ORM 表结构。
    权限不足时此处直接报错（fail fast），避免后续建表时出现
    "type vector does not exist" 的迷惑性错误。
    """
    async with async_engine.begin() as conn:
        await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        await conn.run_sync(Base.metadata.create_all)