"""Long-lived helpers that tools share (voice, indexes, search, data APIs, reminders,
the browser, contacts, WhatsApp, notifications, memory, mail, the calendar, and MCP
servers)."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import Settings
from jarvis.core.meaning import Embedder, MeaningIndex
from jarvis.core.semantic_routing import SemanticRouter
from jarvis.storage.db import Database
from jarvis.storage.repositories import HistoryLog, Preferences
from jarvis.tools.apps.index import AppIndex, AppStore
from jarvis.tools.browser.session import BrowserManager
from jarvis.tools.calendar.feed import Calendar
from jarvis.tools.data.hub import DataHub
from jarvis.tools.files.index import FileIndex
from jarvis.tools.mail.mailbox import Mailbox
from jarvis.tools.mcp.hub import McpHub
from jarvis.tools.memory import MemoryStore
from jarvis.tools.messaging.contacts import ContactBook
from jarvis.tools.messaging.whatsapp import WhatsApp, WhatsAppDesktop, WhatsAppWeb
from jarvis.tools.notifications.store import Notifications
from jarvis.tools.system.reminders import Reminders
from jarvis.tools.web.search import DuckDuckGoSearch, SearchBackend
from jarvis.voice.tts.base import TTSEngine
from jarvis.voice.tts.factory import build_tts


@dataclass
class Services:
    tts: TTSEngine
    apps: AppIndex
    files: FileIndex
    search: SearchBackend
    data: DataHub
    reminders: Reminders
    browser: BrowserManager
    contacts: ContactBook
    whatsapp: WhatsApp
    notifications: Notifications
    memory: MemoryStore
    mail: Mailbox
    calendar: Calendar
    mcp: McpHub
    semantic: SemanticRouter | None = None
    meaning: MeaningIndex | None = None  # memories and past commands by meaning
    history: HistoryLog | None = None  # set by build_app when not given
    prefs: Preferences | None = None  # small settings Jarvis keeps (set by build_app)

    async def aclose(self) -> None:
        await self.mcp.aclose()
        await self.browser.aclose()
        await self.data.aclose()


def build_services(settings: Settings, db: Database) -> Services:
    browser = BrowserManager(settings)
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
        data=DataHub(db, settings),
        reminders=Reminders(db),
        browser=browser,
        contacts=ContactBook(db, settings.contacts),
        whatsapp=WhatsApp(
            WhatsAppWeb(browser, Preferences(db), settings.whatsapp),
            WhatsAppDesktop(),
            settings.whatsapp,
        ),
        notifications=Notifications(db, settings.notifications),
        memory=MemoryStore(db),
        mail=Mailbox(settings.mail),
        calendar=Calendar(settings.calendar),
        mcp=McpHub(settings.mcp, log_dir=settings.data_dir / "logs"),
        semantic=SemanticRouter(
            settings.agent, settings.llm.providers["local"].base_url, settings.data_dir / "cache"
        )
        if settings.agent.semantic_routing and "local" in settings.llm.providers
        else None,
        meaning=MeaningIndex(
            db, Embedder(settings.llm.providers["local"].base_url, settings.agent.semantic_model)
        )
        if "local" in settings.llm.providers
        else None,
        history=HistoryLog(db),
        prefs=Preferences(db),
    )
