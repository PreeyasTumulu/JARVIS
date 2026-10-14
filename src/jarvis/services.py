"""Long-lived helpers that tools share (voice, app index, search backend)."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import Settings
from jarvis.tools.apps.index import AppIndex
from jarvis.tools.web.search import DuckDuckGoSearch, SearchBackend
from jarvis.voice.tts.base import TTSEngine
from jarvis.voice.tts.sapi import SapiTTS


@dataclass
class Services:
    tts: TTSEngine
    apps: AppIndex
    search: SearchBackend


def build_services(settings: Settings) -> Services:
    return Services(
        tts=SapiTTS(rate=settings.tts.rate),
        apps=AppIndex(aliases=settings.apps.aliases, threshold=settings.apps.match_threshold),
        search=DuckDuckGoSearch(region=settings.search.region),
    )
