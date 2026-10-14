"""SQLite connection and schema migrations (tracked with PRAGMA user_version)."""

from __future__ import annotations

import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# Append new migrations to the end. Never edit one that has shipped.
MIGRATIONS: list[str] = [
    # 1: preferences, command history, audit log
    """
    CREATE TABLE preferences (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );

    CREATE TABLE command_history (
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL UNIQUE,
        source TEXT NOT NULL,
        input_text TEXT NOT NULL,
        response_text TEXT,
        status TEXT NOT NULL,
        model TEXT,
        iterations INTEGER NOT NULL DEFAULT 0,
        latency_ms INTEGER
    );

    CREATE TABLE audit_log (
        id INTEGER PRIMARY KEY,
        ts TEXT NOT NULL,
        session_id TEXT NOT NULL,
        turn_id TEXT NOT NULL,
        call_id TEXT,
        tool TEXT NOT NULL,
        args_json TEXT,
        risk TEXT,
        decision TEXT NOT NULL,
        confirmed_via TEXT,
        ok INTEGER NOT NULL,
        result_json TEXT,
        error TEXT,
        duration_ms INTEGER
    );

    CREATE INDEX idx_audit_ts ON audit_log (ts);
    CREATE INDEX idx_audit_turn ON audit_log (turn_id);
    CREATE INDEX idx_history_ts ON command_history (ts);
    """,
    # 2: per-stage timings (stt_ms, llm_ms, first_tool_ms, turn_ms, ...) as JSON
    """
    ALTER TABLE command_history ADD COLUMN timings_json TEXT;
    """,
    # 3: persistent app and file indexes
    """
    CREATE TABLE app_index (
        normalized TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        kind TEXT NOT NULL,
        target TEXT NOT NULL,
        exe TEXT
    );

    CREATE TABLE file_index (
        path TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        normalized TEXT NOT NULL,
        is_dir INTEGER NOT NULL,
        size INTEGER NOT NULL,
        modified REAL NOT NULL
    );

    CREATE TABLE index_meta (
        name TEXT PRIMARY KEY,
        built_at TEXT NOT NULL,
        item_count INTEGER NOT NULL
    );
    """,
]


class Database:
    """One SQLite connection shared by the event loop and worker threads.

    Statements go through `execute` / `executemany` (each holds the lock), and multi-statement
    changes use `transaction()`, so background indexing can write while the agent keeps working.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = path
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
        # Autocommit mode; multi-statement changes use explicit transactions.
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()

    @property
    def version(self) -> int:
        row = self.conn.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def migrate(self) -> None:
        for number in range(self.version + 1, len(MIGRATIONS) + 1):
            script = MIGRATIONS[number - 1]
            self.conn.executescript(f"BEGIN;\n{script}\nPRAGMA user_version = {number};\nCOMMIT;")

    def execute(self, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
        with self.lock:
            return self.conn.execute(sql, params).fetchall()

    def executemany(self, sql: str, rows: Iterable[Sequence[Any]]) -> None:
        with self.lock:
            self.conn.executemany(sql, rows)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self.lock:
            self.conn.execute("BEGIN")
            try:
                yield self.conn
            except BaseException:
                self.conn.execute("ROLLBACK")
                raise
            self.conn.execute("COMMIT")

    def close(self) -> None:
        with self.lock:
            self.conn.close()
