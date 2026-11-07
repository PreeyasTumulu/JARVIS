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
    handled_by: str | None = None  # the router stage of the turn (ADR-083)
    ts: str = field(default_factory=utc_now)


class AuditLog:
    """Every tool call, including blocked, denied, and invalid ones."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def record(self, entry: AuditEntry) -> None:
        self._db.execute(
            """
            INSERT INTO audit_log (ts, session_id, turn_id, call_id, tool, args_json, risk,
                                   decision, confirmed_via, ok, result_json, error, duration_ms,
                                   handled_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                entry.handled_by,
            ),
        )

    def recent(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._db.execute("SELECT * FROM audit_log ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(row) for row in reversed(rows)]


class HistoryLog:
    def __init__(self, db: Database) -> None:
        self._db = db

    def between(
        self,
        start: datetime,
        end: datetime,
        *,
        exclude_turn: str | None = None,
        include_stopped: bool = False,
    ) -> list[dict[str, Any]]:
        """Commands from start to end (inclusive), oldest first; stopped ones left out (recall)
        unless asked for (forgetting must find them too)."""
        low = "" if start.year <= 1 else start.astimezone(UTC).isoformat(timespec="milliseconds")
        high = end.astimezone(UTC).isoformat(timespec="milliseconds")
        rows = self._db.execute(
            "SELECT id, ts, turn_id, input_text, response_text FROM command_history "
            "WHERE ts >= ? AND ts <= ? AND status != ? AND turn_id != ? ORDER BY id",
            (low, high, "" if include_stopped else "cancelled", exclude_turn or ""),
        )
        return [dict(row) for row in rows]

    def forget(self, ids: list[int]) -> None:
        """Delete commands for good: the text, its vector, and the audit rows of those turns."""
        with self._db.transaction() as conn:
            for item_id in ids:
                conn.execute(
                    "DELETE FROM audit_log WHERE turn_id = "
                    "(SELECT turn_id FROM command_history WHERE id = ?)",
                    (item_id,),
                )
                conn.execute("DELETE FROM command_history WHERE id = ?", (item_id,))
                conn.execute(
                    "DELETE FROM embeddings WHERE kind = 'history' AND ref_id = ?", (item_id,)
                )

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
        handled_by: str | None = None,
    ) -> None:
        self._db.execute(
            """
            INSERT INTO command_history (ts, session_id, turn_id, source, input_text,
                                         response_text, status, model, iterations, latency_ms,
                                         timings_json, handled_by)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                handled_by,
            ),
        )

    def add_timings(self, turn_id: str, extra: dict[str, int]) -> None:
        """Add stage times measured after the turn ended (first audio, speech) to its row."""
        rows = self._db.execute(
            "SELECT id, timings_json FROM command_history WHERE turn_id = ? ORDER BY id DESC "
            "LIMIT 1",
            (turn_id,),
        )
        if not rows:
            return
        timings = json.loads(rows[0]["timings_json"] or "{}")
        timings.update(extra)
        self._db.execute(
            "UPDATE command_history SET timings_json = ? WHERE id = ?",
            (to_json(timings), rows[0]["id"]),
        )

    def ids(self) -> list[int]:
        return [int(row[0]) for row in self._db.execute("SELECT id FROM command_history")]

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
