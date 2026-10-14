"""Index of installed apps and fuzzy matching of spoken names.

Sources: the shell:AppsFolder list (`Get-StartApps`, covers packaged and classic apps) and
Start Menu shortcuts as a backup. Phase 3 persists this index in SQLite; for now it is built
lazily in memory on first use.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from rapidfuzz import fuzz, process

log = logging.getLogger(__name__)

AppKind = Literal["appsfolder", "shortcut"]
Source = Callable[[], list["AppEntry"]]

_SKIP_SHORTCUT = re.compile(
    r"uninstall|readme|read me|help|documentation|release notes|license|website|manual",
    re.IGNORECASE,
)
_NOISE = re.compile(r"\((x64|x86|64-bit|32-bit|user)\)|[^\w\s+#]", re.IGNORECASE)


@dataclass(frozen=True)
class AppEntry:
    name: str
    target: str  # AppUserModelID for appsfolder, .lnk path for shortcut
    kind: AppKind


@dataclass(frozen=True)
class AppMatch:
    entry: AppEntry | None
    score: float
    candidates: list[tuple[str, float]] = field(default_factory=list)
    ambiguous: bool = False


def normalize(name: str) -> str:
    return " ".join(_NOISE.sub(" ", name).casefold().split())


class AppIndex:
    def __init__(
        self,
        sources: Sequence[Source] | None = None,
        *,
        aliases: dict[str, str] | None = None,
        threshold: float = 75,
    ) -> None:
        self._sources = list(sources) if sources is not None else [scan_start_apps, scan_shortcuts]
        self._aliases = {normalize(k): v for k, v in (aliases or {}).items()}
        self._threshold = threshold
        self._entries: dict[str, AppEntry] | None = None
        self._lock = asyncio.Lock()

    async def entries(self) -> dict[str, AppEntry]:
        """Normalized name to entry. Built on first use, then cached."""
        async with self._lock:
            if self._entries is None:
                self._entries = await asyncio.to_thread(self._build)
            return self._entries

    async def refresh(self) -> int:
        async with self._lock:
            self._entries = await asyncio.to_thread(self._build)
            return len(self._entries)

    async def get(self, exact_name: str) -> AppEntry | None:
        return (await self.entries()).get(normalize(exact_name))

    async def match(self, spoken: str) -> AppMatch:
        entries = await self.entries()
        query = normalize(spoken)
        query = normalize(self._aliases.get(query, query))
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

    def _build(self) -> dict[str, AppEntry]:
        entries: dict[str, AppEntry] = {}
        for source in self._sources:
            try:
                found = source()
            except Exception:
                log.exception("App source %s failed", getattr(source, "__name__", source))
                continue
            for entry in found:
                entries.setdefault(normalize(entry.name), entry)  # earlier sources win
        log.info("App index built with %d apps", len(entries))
        return entries


def scan_start_apps() -> list[AppEntry]:
    """Every app in shell:AppsFolder, via PowerShell's Get-StartApps."""
    command = (
        "[Console]::OutputEncoding = [Text.Encoding]::UTF8; "
        "Get-StartApps | Select-Object Name, AppID | ConvertTo-Json -Compress"
    )
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        timeout=30,
        check=True,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    data = json.loads(completed.stdout.decode("utf-8", errors="replace") or "[]")
    items = data if isinstance(data, list) else [data]
    return [
        AppEntry(name=item["Name"], target=item["AppID"], kind="appsfolder")
        for item in items
        if item.get("Name") and item.get("AppID")
    ]


def scan_shortcuts() -> list[AppEntry]:
    """Start Menu .lnk files for all users and the current user."""
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
