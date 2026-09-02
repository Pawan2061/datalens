"""Export DataLens conversation, query, and model-usage records as one JSON file.

The export deliberately reads only the conversation and usage-related tables.
It does not export connection definitions, API-tool credentials, password
hashes, or other authentication secrets.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg

from app.config import settings


TABLES = ("sessions", "analytics_events", "usage_logs")


def _json_value(value: Any) -> Any:
    """Normalize values returned by psycopg/JSONB for json.dump."""
    if isinstance(value, str):
        return value
    if isinstance(value, (dict, list, int, float, bool)) or value is None:
        return value
    return str(value)


def _parse_json(value: Any) -> Any:
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    return value


def _schema(cur) -> dict[str, list[dict[str, str]]]:
    cur.execute(
        """
        SELECT table_name, column_name, data_type
        FROM information_schema.columns
        WHERE table_name = ANY(%s)
        ORDER BY table_name, ordinal_position
        """,
        [list(TABLES)],
    )
    result: dict[str, list[dict[str, str]]] = {table: [] for table in TABLES}
    for table, column, data_type in cur.fetchall():
        result[table].append({"name": column, "type": data_type})
    return result


def _read_rows(cur, table: str) -> list[dict[str, Any]]:
    cur.execute(f"SELECT * FROM {table}")
    columns = [desc.name for desc in cur.description]
    return [
        {column: _json_value(value) for column, value in zip(columns, row)}
        for row in cur.fetchall()
    ]


def _sql_queries(assistant_message: dict[str, Any]) -> list[dict[str, Any]]:
    queries: list[dict[str, Any]] = []
    seen: set[str] = set()
    for step in assistant_message.get("steps") or []:
        if not isinstance(step, dict) or not step.get("sql"):
            continue
        sql = str(step["sql"])
        if sql in seen:
            continue
        seen.add(sql)
        queries.append(
            {
                "step_type": step.get("type", ""),
                "sql": sql,
                "step_content": step.get("content", ""),
                "timestamp": step.get("timestamp"),
            }
        )
    return queries


def _answer_text(assistant_message: dict[str, Any]) -> str:
    insight = assistant_message.get("insightResult") or {}
    summary = insight.get("summary") or {}
    return (
        summary.get("narrative")
        or assistant_message.get("content")
        or assistant_message.get("streamingNarrative")
        or ""
    )


def _normalized_turns(sessions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    turns: list[dict[str, Any]] = []
    for session in sessions:
        messages = _parse_json(session.get("messages")) or []
        pending_user: dict[str, Any] | None = None
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") == "user":
                pending_user = message
                continue
            if message.get("role") != "assistant":
                continue

            insight = message.get("insightResult") or {}
            metadata = insight.get("execution_metadata") or {}
            summary = insight.get("summary") or {}
            turns.append(
                {
                    "session_id": session.get("id"),
                    "workspace_id": session.get("workspace_id"),
                    "user_id": session.get("user_id"),
                    "session_title": session.get("title"),
                    "user_message_id": (pending_user or {}).get("id"),
                    "user_query": (pending_user or {}).get("content", ""),
                    "user_timestamp": (pending_user or {}).get("timestamp"),
                    "assistant_message_id": message.get("id"),
                    "assistant_timestamp": message.get("timestamp"),
                    "answer_text": _answer_text(message),
                    "answer_title": summary.get("title", ""),
                    "analysis_mode": message.get("analysisMode", ""),
                    "model_used": metadata.get("model_name", "") or None,
                    "execution_metadata": metadata,
                    "generated_sql": _sql_queries(message),
                }
            )
            pending_user = None
    return turns


def _time_range(rows: list[dict[str, Any]], field: str) -> dict[str, str | None]:
    values = sorted(str(row.get(field)) for row in rows if row.get(field))
    return {"from": values[0] if values else None, "to": values[-1] if values else None}


def build_export() -> dict[str, Any]:
    dsn = re.sub(r"^postgresql\+psycopg://", "postgresql://", settings.database_url)
    if not dsn:
        raise RuntimeError("DATABASE_URL is not configured")

    with psycopg.connect(dsn, connect_timeout=30) as conn:
        with conn.cursor() as cur:
            # The export must never mutate the production database.
            cur.execute("SET TRANSACTION READ ONLY")
            schema = _schema(cur)
            sessions = _read_rows(cur, "sessions")
            analytics_events = _read_rows(cur, "analytics_events")
            usage_logs = _read_rows(cur, "usage_logs")

            cur.execute("SELECT id, email, name, role FROM users ORDER BY id")
            user_directory = [
                {"id": row[0], "email": row[1], "name": row[2], "role": row[3]}
                for row in cur.fetchall()
            ]
            cur.execute("SELECT id, name FROM workspaces ORDER BY id")
            workspace_directory = [
                {"id": row[0], "name": row[1]} for row in cur.fetchall()
            ]
            conn.rollback()

    for session in sessions:
        session["messages"] = _parse_json(session.get("messages")) or []
    for event in analytics_events:
        event["step_timings"] = _parse_json(event.get("step_timings")) or {}

    turns = _normalized_turns(sessions)
    role_counts = Counter(
        message.get("role", "")
        for session in sessions
        for message in session.get("messages", [])
        if isinstance(message, dict)
    )
    analytics_models = Counter(
        event.get("model_name") or "(not recorded)" for event in analytics_events
    )
    usage_models = Counter(
        log.get("model_name") or "(not recorded)" for log in usage_logs
    )
    transcript_models = Counter(
        turn.get("model_used") or "(not recorded)" for turn in turns
    )

    return {
        "export": {
            "format": "datalens-conversations-v1",
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "source": "DataLens PostgreSQL persistence database",
            "scope": {
                "included_tables": list(TABLES),
                "included_user_fields": ["id", "email", "name", "role"],
                "included_workspace_fields": ["id", "name"],
                "excluded": [
                    "password_hash",
                    "connection credentials and connection configs",
                    "API-tool authentication configs",
                    "unrelated application tables",
                ],
                "join_note": (
                    "analytics_events does not contain session_id; it is exported as a "
                    "separate query log. Per-turn model and SQL fields are derived from "
                    "sessions.messages.insightResult and assistant steps."
                ),
            },
            "counts": {
                "sessions": len(sessions),
                "sessions_with_messages": sum(bool(s.get("messages")) for s in sessions),
                "messages": sum(len(s.get("messages", [])) for s in sessions),
                "user_messages": role_counts.get("user", 0),
                "assistant_messages": role_counts.get("assistant", 0),
                "normalized_turns": len(turns),
                "analytics_events": len(analytics_events),
                "usage_logs": len(usage_logs),
            },
            "time_ranges": {
                "sessions": {
                    "created_at": _time_range(sessions, "created_at"),
                    "updated_at": _time_range(sessions, "updated_at"),
                },
                "analytics_events": _time_range(analytics_events, "timestamp"),
                "usage_logs": _time_range(usage_logs, "timestamp"),
            },
            "model_distributions": {
                "transcript_turns": dict(transcript_models),
                "analytics_events": dict(analytics_models),
                "usage_logs": dict(usage_models),
            },
        },
        "schema": schema,
        "user_directory": user_directory,
        "workspace_directory": workspace_directory,
        "conversations": sessions,
        "query_turns": turns,
        "analytics_events": analytics_events,
        "usage_logs": usage_logs,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("exports/datalens_conversations_export.json"),
    )
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    payload = build_export()
    args.output.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "output": str(args.output),
                "sessions": payload["export"]["counts"]["sessions"],
                "query_turns": payload["export"]["counts"]["normalized_turns"],
                "analytics_events": payload["export"]["counts"]["analytics_events"],
                "usage_logs": payload["export"]["counts"]["usage_logs"],
                "bytes": args.output.stat().st_size,
            }
        )
    )


if __name__ == "__main__":
    main()
