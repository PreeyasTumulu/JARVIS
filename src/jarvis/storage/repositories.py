"""Small typed wrappers over the SQLite tables."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from jarvis.storage.db import Database

RESULT_JSON_LIMIT = 2000


def utc_now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def to_json(value: Any, limit: int | None = None) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str)
    if limit is not None and len(text) > limit:
        return text[:limit] + "...(truncated)"
    return text


@dataclass(frozen=True)
class AuditEntry:
    session_id: str
    turn_id: str
    tool: str
    decision: str
    ok: bool
    call_id: str | None = None
    args: dict[str, Any] | None = None
    risk: str | None = None
    confirmed_via: str | None = None
    result: Any = None
    error: str | None = None
    duration_ms: int | None = None
    ts: str = field(default_factory=utc_now)


class AuditLog:
    """Every tool call, including blocked, denied, and invalid ones."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, entry: AuditEntry) -> None:
        self._db.execute(
            """
            INSERT INTO audit_log (ts, session_id, turn_id, call_id, tool, args_json, risk,
                                   decision, confirmed_via, ok, result_json, error, duration_ms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                entry.ts,
                entry.session_id,
                entry.turn_id,
                entry.call_id,
                entry.tool,
                None if entry.args is None else to_json(entry.args),
                entry.risk,
                entry.decision,
                entry.confirmed_via,
                int(entry.ok),
                None if entry.result is None else to_json(entry.result, RESULT_JSON_LIMIT),
                entry.error,
                entry.duration_ms,
            ),
        )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in reversed(rows)]


class HistoryLog:
    def __init__(self, db: Database) -> None:
        self._db = db

    def record(
        self,
        *,
        session_id: str,
        turn_id: str,
        source: str,
        input_text: str,
        response_text: str,
        status: str,
        model: str | None,
        iterations: int,
        latency_ms: int,
        timings: dict[str, int] | None = None,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO command_history (ts, session_id, turn_id, source, input_text,
                                         response_text, status, model, iterations, latency_ms,
                                         timings_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                utc_now(),
                session_id,
                turn_id,
                source,
                input_text,
                response_text,
                status,
                model,
                iterations,
                latency_ms,
                None if timings is None else to_json(timings),
            ),
        )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM command_history ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in reversed(rows)]


class Preferences:
    def __init__(self, db: Database) -> None:
        self._db = db

    def get(self, key: str, default: Any = None) -> Any:
        rows = self._db.execute("SELECT value_json FROM preferences WHERE key = ?", (key,))
        return json.loads(rows[0][0]) if rows else default

    def set(self, key: str, value: Any) -> None:
        self._db.execute(
            """
            INSERT INTO preferences (key, value_json, updated_at) VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json,
                                           updated_at = excluded.updated_at
            """,
            (key, to_json(value), utc_now()),
        )
