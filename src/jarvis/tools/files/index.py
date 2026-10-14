"""Find files by name inside the allowed folders.

Uses Everything (voidtools) through es.exe when it is installed, because it is instant and
always current. Otherwise Jarvis keeps its own index in SQLite: built on first use (a few
seconds for about 50,000 files), then rebuilt in the background when it gets old.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
import shutil
import subprocess
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from rapidfuzz import fuzz, process

from jarvis.config import FilesSettings
from jarvis.storage.db import Database
from jarvis.tools.files.guard import FileGuard

log = logging.getLogger(__name__)

_FILLER = {
    "my", "the", "a", "an", "file", "files", "document", "documents", "doc", "please", "that",
    "this", "called", "named", "latest", "last", "recent", "folder", "find", "open", "show",
}  # fmt: skip
_SPLIT = re.compile(r"[^\w]+")
MIN_SCORE = 60.0


@dataclass(frozen=True)
class FileHit:
    path: str
    name: str
    is_dir: bool
    size: int
    modified: str  # ISO date
    score: float


def normalize(text: str) -> str:
    return " ".join(_SPLIT.sub(" ", text.casefold()).split())


def query_words(query: str) -> list[str]:
    words = normalize(query).split()
    useful = [w for w in words if w not in _FILLER]
    return useful or words


def rank(
    words: list[str],
    rows: Iterable[tuple[str, str, bool, int, float]],
    *,
    kind: str = "any",
    limit: int = 5,
) -> list[FileHit]:
    """Score (path, name, is_dir, size, modified) rows against the query words."""
    query = " ".join(words)
    now = time.time()
    hits: list[FileHit] = []
    for path, name, is_dir, size, modified in rows:
        if (kind == "file" and is_dir) or (kind == "folder" and not is_dir):
            continue
        full = normalize(name)
        stem = normalize(Path(name).stem) or full
        folder = normalize(str(Path(path).parent))
        in_name = sum(1 for word in words if word in full)
        in_folder = sum(1 for word in words if word not in full and word in folder)
        score = fuzz.WRatio(query, stem) + 8 * in_name + 4 * in_folder
        if words and in_name + in_folder == len(words):
            score += 10  # every word is in the name or its folders ("jarvis readme")
        age_days = max(0.0, (now - modified) / 86400)
        score += max(0.0, 5 - age_days / 30)  # slight preference for recent files
        if score >= MIN_SCORE:
            when = datetime.fromtimestamp(modified).date().isoformat()
            hits.append(FileHit(path, name, is_dir, size, when, round(score, 1)))
    hits.sort(key=lambda hit: hit.score, reverse=True)
    return hits[:limit]


class EverythingSearch:
    """Everything's command line client. Only results inside the allowed folders are kept."""

    def __init__(self, exe: Path) -> None:
        self._exe = exe

    @staticmethod
    def find() -> Path | None:
        candidates = [shutil.which("es")] + [
            str(Path(base) / "Everything" / "es.exe")
            for base in (
                os.environ.get("PROGRAMFILES", ""),
                os.environ.get("PROGRAMFILES(X86)", ""),
            )
            if base
        ]
        for candidate in candidates:
            if candidate and Path(candidate).is_file():
                return Path(candidate)
        return None

    def search(self, words: list[str], limit: int = 300) -> list[Path]:
        """Blocking. Returns [] if Everything is not running, so the caller can fall back."""
        try:
            completed = subprocess.run(
                [str(self._exe), "-n", str(limit), "-sort", "date-modified-descending", *words],
                capture_output=True,
                timeout=10,
                creationflags=subprocess.CREATE_NO_WINDOW,
            )
        except (OSError, subprocess.TimeoutExpired):
            return []
        if completed.returncode != 0:
            return []
        lines = completed.stdout.decode("utf-8", errors="replace").splitlines()
        return [Path(line.strip()) for line in lines if line.strip()]


class FileIndex:
    def __init__(
        self,
        db: Database,
        guard: FileGuard,
        cfg: FilesSettings,
        everything: EverythingSearch | None = None,
    ) -> None:
        self._db = db
        self.guard = guard
        self._cfg = cfg
        self._everything = everything
        self._skip = {name.casefold() for name in cfg.skip_dirs}
        self._rebuild_task: asyncio.Task[int] | None = None
        self._lock = asyncio.Lock()

    @classmethod
    def from_settings(cls, db: Database, cfg: FilesSettings) -> FileIndex:
        exe = EverythingSearch.find() if cfg.everything == "auto" else None
        return cls(db, FileGuard(cfg), cfg, EverythingSearch(exe) if exe else None)

    @property
    def backend(self) -> str:
        return "everything" if self._everything else "index"

    async def search(self, query: str, *, kind: str = "any", limit: int = 5) -> list[FileHit]:
        words = query_words(query)
        if not words:
            return []
        if self._everything is not None:
            paths = await asyncio.to_thread(self._everything.search, words)
            rows = [row for row in map(self._stat_row, paths) if row is not None]
            if rows:
                return rank(words, rows, kind=kind, limit=limit)
        await self.ensure_ready()
        rows = await asyncio.to_thread(self._candidates, words)
        return rank(words, rows, kind=kind, limit=limit)

    async def find_by_name(self, name: str) -> list[str]:
        """Exact file name matches (any folder), most recently modified first."""
        await self.ensure_ready()
        rows = self._db.execute(
            "SELECT path FROM file_index WHERE name = ? COLLATE NOCASE ORDER BY modified DESC",
            (name,),
        )
        return [row[0] for row in rows]

    async def ensure_ready(self) -> None:
        built = self._built_at()
        if built is None:
            async with self._lock:
                if self._built_at() is None:
                    await self.rebuild()
        stale = built is not None and built < datetime.now(UTC) - timedelta(
            hours=self._cfg.index_max_age_hours
        )
        if stale and (self._rebuild_task is None or self._rebuild_task.done()):
            self._rebuild_task = asyncio.create_task(self.rebuild())

    async def rebuild(self) -> int:
        started = time.perf_counter()
        rows = await asyncio.to_thread(self._scan)
        await asyncio.to_thread(self._save, rows)
        log.info("File index: %d entries in %.1fs", len(rows), time.perf_counter() - started)
        return len(rows)

    def _built_at(self) -> datetime | None:
        rows = self._db.execute("SELECT built_at FROM index_meta WHERE name = 'files'")
        return datetime.fromisoformat(rows[0][0]) if rows else None

    def _scan(self) -> list[tuple[str, str, str, int, int, float]]:
        rows: list[tuple[str, str, str, int, int, float]] = []
        stack = list(self.guard.roots)
        while stack and len(rows) < self._cfg.max_indexed_files:
            folder = stack.pop()
            try:
                entries = list(os.scandir(folder))
            except OSError:
                continue
            for entry in entries:
                name = entry.name
                if name.startswith("~$"):
                    continue  # Office lock files
                try:
                    is_dir = entry.is_dir(follow_symlinks=False)
                    info = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                if is_dir:
                    if name.casefold() in self._skip or name.startswith("."):
                        continue
                    stack.append(Path(entry.path))
                rows.append(
                    (entry.path, name, normalize(name), int(is_dir), info.st_size, info.st_mtime)
                )
        return rows

    def _save(self, rows: list[tuple[str, str, str, int, int, float]]) -> None:
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM file_index")
            conn.executemany(
                "INSERT OR REPLACE INTO file_index "
                "(path, name, normalized, is_dir, size, modified) VALUES (?, ?, ?, ?, ?, ?)",
                rows,
            )
            conn.execute(
                "INSERT OR REPLACE INTO index_meta (name, built_at, item_count) VALUES (?, ?, ?)",
                ("files", datetime.now(UTC).isoformat(), len(rows)),
            )

    def _candidates(self, words: list[str]) -> list[tuple[str, str, bool, int, float]]:
        clause = " OR ".join("normalized LIKE ?" for _ in words)
        rows = self._db.execute(
            f"SELECT path, name, is_dir, size, modified FROM file_index WHERE {clause} LIMIT 5000",
            [f"%{word}%" for word in words],
        )
        if not rows:  # maybe a typo: fuzzy match against every name
            everything = self._db.execute(
                "SELECT path, name, is_dir, size, modified, normalized FROM file_index"
            )
            names = [row["normalized"] for row in everything]
            best = process.extract(" ".join(words), names, scorer=fuzz.WRatio, limit=50)
            rows = [everything[index] for _, score, index in best if score >= 70]
        return [(r["path"], r["name"], bool(r["is_dir"]), r["size"], r["modified"]) for r in rows]

    def _stat_row(self, path: Path) -> tuple[str, str, bool, int, float] | None:
        resolved = path.resolve(strict=False)
        if not self.guard.allows(resolved):
            return None
        with contextlib.suppress(OSError):
            info = path.stat()
            return (str(path), path.name, path.is_dir(), info.st_size, info.st_mtime)
        return None
