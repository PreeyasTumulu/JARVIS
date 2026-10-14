"""Index of installed apps, fuzzy matching of spoken names, and matching apps to open windows.

Sources: one PowerShell call lists the shell:AppsFolder entries (`Get-StartApps`, packaged and
classic apps) plus Start Menu shortcuts with their target executables. The result is stored in
SQLite and reused for a week. A name that matches nothing triggers one refresh, so newly
installed apps are found without a manual rebuild.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
import time
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process

from jarvis.storage.db import Database

log = logging.getLogger(__name__)

AppKind = Literal["appsfolder", "shortcut"]
Source = Callable[[], list["AppEntry"]]

_SKIP_SHORTCUT = re.compile(
    r"uninstall|readme|read me|help|documentation|release notes|license|website|manual",
    re.IGNORECASE,
)
_NOISE = re.compile(r"\((x64|x86|64-bit|32-bit|user)\)|[^\w\s+#]", re.IGNORECASE)
# Window titles separate parts with " - ", an en dash, an em dash, or " | ".
_TITLE_SEPARATORS = re.compile("\\s+[-|\u2013\u2014]\\s+")
_DIRTY_TITLE = re.compile("(^\\*)|(\\*$)|(^\u25cf)|\\bunsaved\\b", re.IGNORECASE)
REFRESH_ON_MISS_S = 600


@dataclass(frozen=True)
class AppEntry:
    name: str
    target: str  # AppUserModelID for appsfolder, .lnk path for shortcut
    kind: AppKind
    exe: str | None = None  # executable name without extension, when known


@dataclass(frozen=True)
class AppMatch:
    entry: AppEntry | None
    score: float
    candidates: list[tuple[str, float]] = field(default_factory=list)
    ambiguous: bool = False


def normalize(name: str) -> str:
    return " ".join(_NOISE.sub(" ", name).casefold().split())


class AppStore:
    """Persists the app index in SQLite."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def load(self, max_age: timedelta) -> list[AppEntry] | None:
        meta = self._db.execute("SELECT built_at FROM index_meta WHERE name = 'apps'")
        if not meta or datetime.fromisoformat(meta[0][0]) < datetime.now(UTC) - max_age:
            return None
        rows = self._db.execute("SELECT name, target, kind, exe FROM app_index")
        return [AppEntry(r["name"], r["target"], r["kind"], r["exe"]) for r in rows]

    def save(self, entries: Iterable[AppEntry]) -> None:
        items = list(entries)
        with self._db.transaction() as conn:
            conn.execute("DELETE FROM app_index")
            conn.executemany(
                "INSERT OR REPLACE INTO app_index (normalized, name, kind, target, exe) "
                "VALUES (?, ?, ?, ?, ?)",
                [(normalize(e.name), e.name, e.kind, e.target, e.exe) for e in items],
            )
            conn.execute(
                "INSERT OR REPLACE INTO index_meta (name, built_at, item_count) VALUES (?, ?, ?)",
                ("apps", datetime.now(UTC).isoformat(), len(items)),
            )


class AppIndex:
    def __init__(
        self,
        sources: Sequence[Source] | None = None,
        *,
        aliases: dict[str, str] | None = None,
        process_names: dict[str, str] | None = None,
        threshold: float = 75,
        store: AppStore | None = None,
        max_age: timedelta = timedelta(days=7),
    ) -> None:
        self._sources = list(sources) if sources is not None else [scan_start_menu, scan_shortcuts]
        self._aliases = {normalize(k): v for k, v in (aliases or {}).items()}
        self._process_names = {normalize(k): v for k, v in (process_names or {}).items()}
        self._threshold = threshold
        self._store = store
        self._max_age = max_age
        self._entries: dict[str, AppEntry] | None = None
        self._last_refresh: float | None = None  # monotonic time; None means never this session
        self._lock = asyncio.Lock()

    async def entries(self) -> dict[str, AppEntry]:
        """Normalized name to entry: memory, then SQLite, then a fresh scan."""
        async with self._lock:
            if self._entries is None:
                stored = await asyncio.to_thread(self._load_stored)
                self._entries = stored if stored else await asyncio.to_thread(self._build)
            return self._entries

    async def refresh(self) -> int:
        async with self._lock:
            self._entries = await asyncio.to_thread(self._build)
            return len(self._entries)

    async def get(self, exact_name: str) -> AppEntry | None:
        return (await self.entries()).get(normalize(exact_name))

    async def match(self, spoken: str) -> AppMatch:
        result = self._match(await self.entries(), spoken)
        if result.entry is None and self._may_refresh():
            await self.refresh()  # maybe the app was installed after the index was built
            result = self._match(await self.entries(), spoken)
        return result

    def canonical(self, spoken: str) -> str:
        """Apply aliases, so "vs code" becomes "Visual Studio Code"."""
        return self._aliases.get(normalize(spoken), spoken)

    def process_name(self, entry: AppEntry | None, spoken: str) -> str | None:
        """The executable to look for in open windows, from config or the index."""
        for name in (entry.name if entry else None, self.canonical(spoken), spoken):
            if name and normalize(name) in self._process_names:
                return self._process_names[normalize(name)]
        return entry.exe if entry else None

    def _match(self, entries: dict[str, AppEntry], spoken: str) -> AppMatch:
        query = normalize(self.canonical(spoken))
        if not query:
            return AppMatch(None, 0)
        if query in entries:
            return AppMatch(entries[query], 100)

        results = process.extract(query, list(entries), scorer=fuzz.WRatio, limit=5)
        candidates = [(entries[key].name, float(score)) for key, score, _ in results]
        if not results or results[0][1] < self._threshold:
            return AppMatch(None, results[0][1] if results else 0, candidates)

        best_key, best_score, _ = results[0]
        close = [key for key, score, _ in results[1:] if score >= best_score - 2]
        return AppMatch(entries[best_key], float(best_score), candidates, ambiguous=bool(close))

    def _may_refresh(self) -> bool:
        # time.monotonic() counts from boot, so "0 means never" would break right after a reboot.
        last = self._last_refresh
        return last is None or time.monotonic() - last > REFRESH_ON_MISS_S

    def _load_stored(self) -> dict[str, AppEntry] | None:
        if self._store is None:
            return None
        loaded = self._store.load(self._max_age)
        return {normalize(e.name): e for e in loaded} if loaded else None

    def _build(self) -> dict[str, AppEntry]:
        self._last_refresh = time.monotonic()
        entries: dict[str, AppEntry] = {}
        for source in self._sources:
            try:
                found = source()
            except Exception:
                log.exception("App source %s failed", getattr(source, "__name__", source))
                continue
            for entry in found:
                entries.setdefault(normalize(entry.name), entry)  # earlier sources win
        if self._store is not None and entries:
            self._store.save(entries.values())
        log.info("App index built with %d apps", len(entries))
        return entries


_SCAN_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$shell = New-Object -ComObject WScript.Shell
$roots = @("$env:ProgramData\Microsoft\Windows\Start Menu\Programs",
           "$env:APPDATA\Microsoft\Windows\Start Menu\Programs")
$links = foreach ($root in $roots) {
  if (Test-Path $root) {
    Get-ChildItem -Path $root -Recurse -Filter *.lnk -ErrorAction SilentlyContinue |
    ForEach-Object {
      try { [pscustomobject]@{ Name = $_.BaseName; Path = $_.FullName;
                               Target = $shell.CreateShortcut($_.FullName).TargetPath } } catch {}
    }
  }
}
$apps = Get-StartApps | Select-Object Name, AppID
@{ apps = @($apps); links = @($links) } | ConvertTo-Json -Depth 3 -Compress
"""


def scan_start_menu() -> list[AppEntry]:
    """shell:AppsFolder apps, with executables filled in from AppIDs or Start Menu shortcuts."""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SCAN_SCRIPT],
        capture_output=True,
        timeout=60,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    data = json.loads(completed.stdout.decode("utf-8", errors="replace") or "{}")
    link_exe: dict[str, str] = {}
    shortcuts: list[AppEntry] = []
    for link in data.get("links") or []:
        name, target = link.get("Name"), link.get("Target") or ""
        if not name or _SKIP_SHORTCUT.search(name):
            continue
        exe = Path(target).stem if target.casefold().endswith(".exe") else None
        if exe:
            link_exe.setdefault(normalize(name), exe)
        shortcuts.append(AppEntry(name=name, target=link["Path"], kind="shortcut", exe=exe))

    entries: list[AppEntry] = []
    for app in data.get("apps") or []:
        name, app_id = app.get("Name"), app.get("AppID")
        if not name or not app_id:
            continue
        exe = Path(app_id).stem if app_id.casefold().endswith(".exe") else None
        entries.append(AppEntry(name, app_id, "appsfolder", exe or link_exe.get(normalize(name))))
    return entries + shortcuts


def scan_shortcuts() -> list[AppEntry]:
    """Fallback without PowerShell: Start Menu .lnk names only (no executable names)."""
    roots = [
        Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")),
        Path(os.environ.get("APPDATA", "")),
    ]
    entries: list[AppEntry] = []
    for root in roots:
        folder = root / "Microsoft" / "Windows" / "Start Menu" / "Programs"
        if not folder.is_dir():
            continue
        for link in folder.rglob("*.lnk"):
            if not _SKIP_SHORTCUT.search(link.stem):
                entries.append(AppEntry(name=link.stem, target=str(link), kind="shortcut"))
    return entries


def launch(entry: AppEntry) -> None:
    """Start the app without waiting for it."""
    if entry.kind == "appsfolder":
        # explorer.exe returns immediately (and with exit code 1), so do not check it.
        subprocess.Popen(["explorer.exe", f"shell:AppsFolder\\{entry.target}"])
    else:
        os.startfile(entry.target)  # type: ignore[attr-defined,unused-ignore]


def title_parts(title: str) -> list[str]:
    parts = [normalize(part) for part in _TITLE_SEPARATORS.split(title)]
    return [part for part in parts if part]


def looks_unsaved(title: str) -> bool:
    return bool(_DIRTY_TITLE.search(title.strip()))
