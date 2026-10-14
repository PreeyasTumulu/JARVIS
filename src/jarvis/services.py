"""Long-lived helpers that tools share (voice, app index, file index, search backend)."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import Settings
from jarvis.storage.db import Database
from jarvis.tools.apps.index import AppIndex, AppStore
from jarvis.tools.files.index import FileIndex
from jarvis.tools.web.search import DuckDuckGoSearch, SearchBackend
from jarvis.voice.tts.base import TTSEngine
from jarvis.voice.tts.factory import build_tts


@dataclass
class Services:
    tts: TTSEngine
    apps: AppIndex
    files: FileIndex
    search: SearchBackend


def build_services(settings: Settings, db: Database) -> Services:
    return Services(
        tts=build_tts(settings),
        apps=AppIndex(
            aliases=settings.apps.aliases,
            process_names=settings.apps.process_names,
            threshold=settings.apps.match_threshold,
            store=AppStore(db),
        ),
        files=FileIndex.from_settings(db, settings.files),
        search=DuckDuckGoSearch(region=settings.search.region),
    )
