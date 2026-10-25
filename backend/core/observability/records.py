"""作者：LHF；时间：2026-10-25；作用：统一新终态记录和旧事件日志的只读展示结构。"""

from datetime import datetime, timedelta


def completed_records(rows):
    """新记录原样保留；旧日志只合并已有字段，不补造历史输入输出。"""
    records, starts = [], {}
    for index, row in enumerate(rows):
        if row.get("record_version"):
            records.append(row)
            continue
        event = row.get("event", "")
        stage_id = row.get("stage_id")
        if event in {"turn.started", "stage.started"}:
            starts[stage_id] = row
            continue
        if event not in {
            "stage.completed",
            "stage.failed",
            "trace.summary",
            "llm.context",
        }:
            continue
        if (
            row.get("stage") in {"preparation", "model_output"}
            or stage_id == "agent.debug"
        ):
            continue
        begin = starts.pop(stage_id, {})
        detail = row.get("detail") or {}
        start = begin.get("started_at") or row.get("started_at") or row.get("timestamp")
        duration = row.get("duration_ms", row.get("total_duration_ms"))
        end = row.get("timestamp")
        if start and duration is not None:
            try:
                end = (
                    datetime.fromisoformat(start) + timedelta(milliseconds=duration)
                ).isoformat()
            except (ValueError, TypeError):
                pass
        records.append(
            {
                **row,
                "operation_id": row.get("event_id") or f"legacy_{index}",
                "kind": "model"
                if event == "llm.context"
                else "request"
                if event == "trace.summary"
                else row.get("stage", "agent"),
                "started_at": start,
                "ended_at": end,
                "duration_ms": duration,
                "input": detail.get("request")
                if event == "llm.context"
                else detail.get("input"),
                "output": detail.get("output", detail or None)
                if event != "llm.context"
                else None,
                "metadata": {
                    "legacy": True,
                    "missing_data": "历史未采集；原始内容可能已截断",
                },
            }
        )
    return sorted(
        records,
        key=lambda row: (
            str(row.get("started_at") or ""),
            str(row.get("operation_id") or ""),
        ),
    )
