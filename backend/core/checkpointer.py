"""对话记忆 Checkpointer 全局单例

基于 langgraph-checkpoint-postgres 的 AsyncPostgresSaver:
- 全局唯一实例,进程生命周期内复用连接(不用 from_conn_string 的 with 块方式)
- lifespan 启动时 setup() 自动建表(幂等)
- thread_id = conversations.id,由会话系统分配
"""
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.core.config import settings

_checkpointer: AsyncPostgresSaver | None = None


async def get_checkpointer() -> AsyncPostgresSaver:
    """获取全局 AsyncPostgresSaver(懒加载单例,首次调用时建连 + setup)"""
    global _checkpointer
    if _checkpointer is None:
        conn = await AsyncConnection.connect(
            settings.checkpoint.url,
            autocommit=True,
            prepare_threshold=0,
            row_factory=dict_row,
        )
        _checkpointer = AsyncPostgresSaver(conn=conn)
        await _checkpointer.setup()
    return _checkpointer
