"""作者：LHF；时间：2026-10-25；作用：导出清单、清理两种 thread 并执行统一 Agent 迁移。"""

import argparse
import asyncio
import hashlib
import json
import sys
from datetime import UTC, datetime

import psycopg
from psycopg import sql
from psycopg.rows import dict_row

from backend.core.config import PROJECT_ROOT, settings


def database_url():
    """将 SQLAlchemy asyncpg URL 转为 psycopg URL，不输出凭据。"""
    return settings.database.url.replace("postgresql+asyncpg://", "postgresql://")


def inventory(connection):
    """只读收集目标和关联数据，兼容旧表已删除。"""
    table_exists = connection.execute("SELECT to_regclass('simple_rag_agents') AS name").fetchone()["name"]
    query = "SELECT id FROM agent_index WHERE type = 'simple_rag'"
    if table_exists:
        query += " UNION SELECT id FROM simple_rag_agents"
    ids = [row["id"] for row in connection.execute(query)]
    result = {"agent_ids": ids, "agent_index": [], "simple_rag_agents": [], "conversations": [], "agent_api_keys": []}
    if ids:
        for table in ("agent_index", "simple_rag_agents", "conversations", "agent_api_keys"):
            if table == "simple_rag_agents" and not table_exists:
                continue
            column = "id" if table in {"agent_index", "simple_rag_agents"} else "agent_id"
            result[table] = list(connection.execute(sql.SQL("SELECT * FROM {} WHERE {} = ANY(%s)").format(
                sql.Identifier(table), sql.Identifier(column)), (ids,)))
    return result


def protected_fingerprint(connection):
    """核对 general 及其会话、密钥，忽略本次明确移除的旧轻量规则。"""
    result = {}
    queries = {
        "index": "SELECT * FROM agent_index WHERE type = 'general' ORDER BY id",
        "agents": "SELECT * FROM general_agents ORDER BY id",
        "conversations": "SELECT * FROM conversations WHERE agent_id IN (SELECT id FROM agent_index WHERE type = 'general') ORDER BY id",
        "keys": "SELECT * FROM agent_api_keys WHERE agent_id IN (SELECT id FROM agent_index WHERE type = 'general') ORDER BY id",
    }
    for name, query in queries.items():
        rows = list(connection.execute(query))
        if name == "agents":
            for row in rows:
                rules = row.get("intent_rules") or {}
                if "rules" in rules:
                    rules["rules"] = [item for item in rules["rules"] if item.get("target") != "simple"]
                    row["intent_rules"] = rules
        result[name] = rows
    return hashlib.sha256(json.dumps(result, default=str, sort_keys=True).encode()).hexdigest()


async def clear_checkpoint_threads(conversation_ids):
    """用公开接口清理新旧 thread，独立 checkpoint 数据库同样适用。"""
    from backend.core.checkpointer import close_checkpointer, get_checkpointer

    if not conversation_ids:
        return
    saver = await get_checkpointer()
    try:
        for conversation_id in conversation_ids:
            await saver.adelete_thread(str(conversation_id))
            await saver.adelete_thread(f"memory_v2:{conversation_id}")
    finally:
        await close_checkpointer()


def main():
    """默认只读；显式 --apply 时备份目标数据并执行清理。"""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    with psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=3) as connection:
        data = inventory(connection)
        protected_before = protected_fingerprint(connection)
        counts = {key: len(value) for key, value in data.items()}
        print(json.dumps({"mode": "apply" if args.apply else "dry-run", "counts": counts}, ensure_ascii=False))
        if not args.apply:
            return
        backup = PROJECT_ROOT / "storage/migrations" / datetime.now(UTC).strftime("%Y%m%dT%H%M%S%fZ")
        backup.mkdir(parents=True)
        (backup / "simple-agents.json").write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
        # 先备份 checkpoint 原始行，便于人工恢复；不输出任何内容。
        conversation_ids = [row["id"] for row in data["conversations"]]
        threads = [name for value in conversation_ids for name in (str(value), f"memory_v2:{value}")]
        checkpoint_backup = {}
        with psycopg.connect(settings.checkpoint.url, row_factory=dict_row, connect_timeout=3) as checkpoint_db:
            for table in ("checkpoints", "checkpoint_blobs", "checkpoint_writes"):
                if checkpoint_db.execute("SELECT to_regclass(%s) AS name", (table,)).fetchone()["name"]:
                    checkpoint_backup[table] = list(checkpoint_db.execute(
                        sql.SQL("SELECT * FROM {} WHERE thread_id = ANY(%s)").format(sql.Identifier(table)), (threads,)))
        (backup / "checkpoint-rows.json").write_text(json.dumps(checkpoint_backup, default=lambda value: {"hex": bytes(value).hex()} if isinstance(value, (bytes, memoryview)) else str(value)), encoding="utf-8")
        asyncio.run(clear_checkpoint_threads(conversation_ids))
        migration = PROJECT_ROOT / "backend/sql/migrations/026_remove_simple_agents.sql"
        connection.execute(migration.read_text(encoding="utf-8"), prepare=False)
        if protected_fingerprint(connection) != protected_before:
            raise RuntimeError("general 保护数据核对失败，迁移已回滚")
        connection.commit()
        print(json.dumps({"applied": True, "general_preserved": True,
                          "remaining": len(inventory(connection)["agent_ids"]), "backup": str(backup)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
