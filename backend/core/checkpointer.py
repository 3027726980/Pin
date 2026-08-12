"""对话记忆 Checkpointer 全局单例

基于 langgraph-checkpoint-postgres 的 AsyncPostgresSaver:
- 全局唯一实例,进程生命周期内复用连接(不用 from_conn_string 的 with 块方式)
- lifespan 启动时 setup() 自动建表(幂等)
- thread_id = conversations.id,由会话系统分配
- prune_checkpoints:每轮对话后清理旧快照(仅保留最近 N 轮),防 O(N²) 膨胀
"""
from psycopg import AsyncConnection
from psycopg.rows import dict_row
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from backend.core.config import settings

_checkpointer: AsyncPostgresSaver | None = None


def _count_user_messages(t) -> int:
    """统计 checkpoint 快照中的 user 消息数(= 已进行的对话轮数)

    轮次判定原理:LangGraph 每轮对话 = messages 数组新增一条 user 消息,
    因此按快照中 HumanMessage 的数量即可精确区分轮次边界。
    """
    msgs = t.checkpoint.get("channel_values", {}).get("messages", [])
    return sum(1 for m in msgs if getattr(m, "type", "") == "human")


async def prune_checkpoints(thread_id: str, keep_rounds: int) -> int:
    """清理指定会话的旧 checkpoint,仅保留最近 keep_rounds 轮,返回删除条数

    背景:LangGraph 图每执行一个 super-step 就自动写一条 checkpoint 快照
    (一轮对话 2~N 条),且快照含到此刻为止的全部消息——条数 O(N)×单条 O(N)
    = O(N²) 膨胀;而所有读取(aget_tuple)只用最新一条,旧快照全是死数据。

    实现:按 user 消息数分轮 → 删除 user 数 < (最新轮数 - keep_rounds + 1)
    的 checkpoint 及其 checkpoint_writes(独立 psycopg 连接,不动私有 API)。
    注意:checkpoint_blobs 为 channel 级内容去重共享,保留的 checkpoint 可能
    仍引用,故不删(孤儿 blob 量级有限,可接受)。
    """
    if keep_rounds <= 0:
        return 0
    cp = await get_checkpointer()
    config = {"configurable": {"thread_id": str(thread_id), "checkpoint_ns": ""}}
    tuples = [t async for t in cp.alist(config, limit=1000)]  # newest first
    if not tuples:
        return 0

    newest_user_count = _count_user_messages(tuples[0])
    keep_min_user = newest_user_count - keep_rounds + 1
    if keep_min_user <= 1:
        return 0  # 会话不足 keep_rounds 轮,无需清理

    delete_ids = [
        t.config["configurable"]["checkpoint_id"] for t in tuples
        if _count_user_messages(t) < keep_min_user
    ]
    if not delete_ids:
        return 0

    conn = await AsyncConnection.connect(settings.checkpoint.url, autocommit=True)
    try:
        async with conn.cursor() as cur:
            for cid in delete_ids:
                await cur.execute(
                    "DELETE FROM checkpoint_writes "
                    "WHERE thread_id = %s AND checkpoint_id = %s",
                    (str(thread_id), cid),
                )
                await cur.execute(
                    "DELETE FROM checkpoints "
                    "WHERE thread_id = %s AND checkpoint_id = %s",
                    (str(thread_id), cid),
                )
    finally:
        await conn.close()
    return len(delete_ids)


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
