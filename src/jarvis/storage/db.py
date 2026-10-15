"""SQLite connection, schema migrations (tracked with PRAGMA user_version), and recovery from a
damaged file (moved aside untouched, readable rows copied into a fresh database)."""

from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterable, Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

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
    # 4: data API cache, and timers and reminders
    """
    CREATE TABLE api_cache (
        key TEXT PRIMARY KEY,
        value_json TEXT NOT NULL,
        fetched_at REAL NOT NULL,
        expires_at REAL NOT NULL
    );

    CREATE TABLE reminders (
        id INTEGER PRIMARY KEY,
        kind TEXT NOT NULL,
        message TEXT NOT NULL,
        due_at REAL NOT NULL,
        created_at REAL NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        fired_at REAL
    );

    CREATE INDEX idx_reminders_due ON reminders (status, due_at);
    """,
    # 5: contacts and their spoken aliases (an alias may name several people on purpose)
    """
    CREATE TABLE contacts (
        id INTEGER PRIMARY KEY,
        name TEXT NOT NULL,
        name_key TEXT NOT NULL UNIQUE,
        phone TEXT NOT NULL,
        notes TEXT NOT NULL DEFAULT '',
        created_at TEXT NOT NULL
    );

    CREATE TABLE contact_aliases (
        alias_key TEXT NOT NULL,
        alias TEXT NOT NULL,
        contact_id INTEGER NOT NULL REFERENCES contacts (id) ON DELETE CASCADE,
        PRIMARY KEY (alias_key, contact_id)
    );
    """,
    # 6: notifications from allowed apps (private; deleted after notifications.keep_days)
    """
    CREATE TABLE notifications (
        id INTEGER PRIMARY KEY,
        win_id INTEGER NOT NULL,
        app_id TEXT NOT NULL,
        app TEXT NOT NULL,
        title TEXT NOT NULL,
        body TEXT NOT NULL,
        created_at TEXT NOT NULL,
        seen_at TEXT NOT NULL,
        read_at TEXT,
        UNIQUE (app_id, win_id, created_at)
    );

    CREATE INDEX idx_notifications_created ON notifications (created_at);
    """,
]


class Database:
    """One SQLite connection shared by the event loop and worker threads.

    Statements go through `execute` / `executemany` (each holds the lock), and multi-statement
    changes use `transaction()`, so background indexing can write while the agent keeps working.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = path
        self.recovered_from: Path | None = None  # set when a damaged file was moved aside
        if isinstance(path, Path):
            path.parent.mkdir(parents=True, exist_ok=True)
            if path.exists() and not healthy(path):
                self.recovered_from = set_aside(path)
        # Autocommit mode; multi-statement changes use explicit transactions.
        self.conn = sqlite3.connect(str(path), isolation_level=None, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        if str(path) != ":memory:":
            self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.migrate()
        if self.recovered_from is not None:
            saved = salvage(self.recovered_from, self)
            log.warning(
                "Jarvis's database was damaged. It was moved to %s and a new one was started; "
                "%s rows were copied over. Indexes rebuild themselves.",
                self.recovered_from,
                sum(saved.values()),
            )

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


# What is worth copying out of a damaged database. Indexes and the API cache rebuild themselves.
SALVAGE_TABLES = (
    "preferences",
    "command_history",
    "audit_log",
    "reminders",
    "contacts",
    "contact_aliases",
    "notifications",
)


def healthy(path: Path) -> bool:
    """Whether SQLite can read every page of the file (a quick check takes milliseconds)."""
    try:
        conn = sqlite3.connect(str(path))
        try:
            return bool(conn.execute("PRAGMA quick_check(1)").fetchone()[0] == "ok")
        finally:
            conn.close()
    except sqlite3.DatabaseError:
        return False


def set_aside(path: Path) -> Path:
    """Rename a damaged database (and its WAL files) out of the way, untouched."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = path.with_name(f"{path.name}.corrupt-{stamp}")
    for suffix in ("", "-wal", "-shm"):
        source = Path(f"{path}{suffix}")
        if source.exists():
            source.replace(Path(f"{target}{suffix}"))
    return target


def salvage(broken: Path, db: Database) -> dict[str, int]:
    """Copy every row that can still be read from a damaged database into a fresh one."""
    saved: dict[str, int] = {}
    try:
        old = sqlite3.connect(f"file:{broken.as_posix()}?mode=ro", uri=True)
    except sqlite3.DatabaseError:
        return saved
    try:
        for table in SALVAGE_TABLES:
            saved[table] = _copy_rows(old, db, table)
    finally:
        old.close()
    return saved


def _copy_rows(old: sqlite3.Connection, db: Database, table: str) -> int:
    columns = {row[1] for row in db.execute(f"PRAGMA table_info({table})")}
    copied = 0
    try:
        cursor = old.execute(f"SELECT * FROM {table}")
        names = [name for name in (d[0] for d in cursor.description) if name in columns]
        insert = (
            f"INSERT OR IGNORE INTO {table} ({', '.join(names)}) "
            f"VALUES ({', '.join('?' for _ in names)})"
        )
        positions = [i for i, d in enumerate(cursor.description) if d[0] in columns]
        while rows := cursor.fetchmany(200):
            db.executemany(insert, [[row[i] for i in positions] for row in rows])
            copied += len(rows)
    except sqlite3.DatabaseError as exc:
        log.warning("Stopped copying %s after %d rows: %s", table, copied, exc)
    return copied
