"""Wires settings, storage, model, tools, and the agent into one object every interface uses."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from jarvis.config import Settings
from jarvis.core.agent import Agent
from jarvis.core.channel import ApprovedChannel, UserChannel
from jarvis.core.events import Announcement, EventBus
from jarvis.core.executor import ToolExecutor
from jarvis.llm.client import LLMClient
from jarvis.llm.router import Router
from jarvis.llm.types import ChatModel, ToolCall
from jarvis.services import Services, build_services
from jarvis.storage.db import Database
from jarvis.storage.repositories import AuditLog, HistoryLog, Preferences
from jarvis.storage.retention import run_retention
from jarvis.tools.catalog import build_registry
from jarvis.tools.notifications.store import NotificationWatcher
from jarvis.tools.policy import PolicyGate
from jarvis.tools.registry import Registry
from jarvis.tools.system.clipboard import ClipboardHistory
from jarvis.tools.system.focus import Focus
from jarvis.tools.system.reminders import Reminder, ReminderScheduler, lowered


@dataclass
class App:
    settings: Settings
    db: Database
    audit: AuditLog
    history: HistoryLog
    bus: EventBus
    registry: Registry
    llm: ChatModel
    services: Services
    agent: Agent
    router: Router
    background: list[asyncio.Task[None]] = field(default_factory=list)

    async def run_scheduled(self, item: Reminder) -> str:
        """Run a scheduled action through the policy gate; what to say about it (ADR-087)."""
        plan = item.action or {}
        call = ToolCall(
            id=f"schedule_{item.id}",
            name=str(plan.get("tool", "")),
            arguments=json.dumps(plan.get("args", {}), ensure_ascii=False),
        )
        channel = ApprovedChannel(self.agent.channel, plan.get("approved"))
        outcome = await self.agent.run_call(call, channel, "schedule")
        result = outcome.result
        if result.ok:
            return f"As you asked: {result.speech or 'done'}"
        return f"I couldn't {lowered(item.message)} as scheduled: {result.error}"

    async def start_background(self, announce: Callable[[str], Awaitable[None]]) -> None:
        """Work that runs while chat, voice, or the web UI is open (not one-shot `ask`):
        timers and reminders, watching the notification center, and deleting old history."""
        speaking = asyncio.Lock()

        async def say(text: str) -> None:
            # One at a time: a focus session's summary and the reminder it held fall due
            # together, and neither speech engine queues on its own.
            async with speaking:
                await announce(text)

        async def say_focus(text: str) -> None:
            await self.bus.publish(Announcement(source="focus", text=text))
            await say(text)

        self.background.append(
            asyncio.create_task(run_retention(self.db, self.settings.history), name="retention")
        )
        phone = self.services.phone
        scheduler = ReminderScheduler(
            self.services.reminders,
            self.bus,
            say,
            self.run_scheduled,
            # Your own words to your own phone, asked for when the reminder was set (ADR-098).
            alert_phone=(lambda text: phone.alert(text, ring=True)) if phone else None,
        )
        self.background.append(asyncio.create_task(scheduler.run(), name="reminders"))
        if self.services.focus is not None:
            self.background.append(
                asyncio.create_task(self.services.focus.run(say_focus), name="focus")
            )
        if self.settings.clipboard.history:
            self.services.clipboard = ClipboardHistory(self.settings.clipboard)
            self.background.append(
                asyncio.create_task(self.services.clipboard.run(), name="clipboard")
            )
        settings = self.settings.notifications
        if settings.enabled:
            watcher = NotificationWatcher(self.services.notifications, self.bus, settings.poll_s)
            self.background.append(asyncio.create_task(watcher.run(), name="notifications"))

    async def aclose(self) -> None:
        for task in self.background:
            task.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)
        await self.services.aclose()
        await self.llm.aclose()
        await self.router.aclose()
        self.db.close()


def build_app(
    settings: Settings,
    channel: UserChannel,
    *,
    llm: ChatModel | None = None,
    router: Router | None = None,
    services: Services | None = None,
    registry: Registry | None = None,
    db: Database | None = None,
) -> App:
    db = db or Database(settings.data_dir / "jarvis.db")
    audit = AuditLog(db)
    history = HistoryLog(db)
    bus = EventBus()
    registry = registry or build_registry()
    services = services or build_services(settings, db)
    if services.history is None:
        services.history = history  # recall reads the same command history
    if services.prefs is None:
        services.prefs = Preferences(db)
    if services.focus is None:
        services.focus = Focus(services.reminders, services.notifications, services.prefs)
    llm = llm or LLMClient(settings.llm.active())
    router = router or Router(settings, db)
    services.cloud = services.cloud or router
    services.local_model = services.local_model or llm
    executor = ToolExecutor(
        settings=settings,
        registry=registry,
        policy=PolicyGate(settings.safety),
        audit=audit,
        bus=bus,
    )
    agent = Agent(
        settings=settings,
        llm=llm,
        registry=registry,
        executor=executor,
        history=history,
        bus=bus,
        channel=channel,
        services=services,
        router=router,
    )
    return App(settings, db, audit, history, bus, registry, llm, services, agent, router)
