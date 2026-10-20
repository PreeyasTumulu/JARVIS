"""Long-lived helpers that tools share (voice, indexes, search, data APIs, reminders,
the browser, contacts, WhatsApp, notifications, memory, mail, and the calendar)."""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import Settings
from jarvis.storage.db import Database
from jarvis.storage.repositories import Preferences
from jarvis.tools.apps.index import AppIndex, AppStore
from jarvis.tools.browser.session import BrowserManager
from jarvis.tools.calendar.feed import Calendar
from jarvis.tools.data.hub import DataHub
from jarvis.tools.files.index import FileIndex
from jarvis.tools.mail.mailbox import Mailbox
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

    async def aclose(self) -> None:
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
    )
