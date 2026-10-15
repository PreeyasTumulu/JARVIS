"""Wires settings, storage, model, tools, and the agent into one object every interface uses."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from jarvis.config import Settings
from jarvis.core.agent import Agent
from jarvis.core.channel import UserChannel
from jarvis.core.events import EventBus
from jarvis.core.executor import ToolExecutor
from jarvis.llm.client import LLMClient
from jarvis.llm.types import ChatModel
from jarvis.services import Services, build_services
from jarvis.storage.db import Database
from jarvis.storage.repositories import AuditLog, HistoryLog
from jarvis.tools.catalog import build_registry
from jarvis.tools.policy import PolicyGate
from jarvis.tools.registry import Registry
from jarvis.tools.system.reminders import ReminderScheduler


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
    background: list[asyncio.Task[None]] = field(default_factory=list)

    async def start_reminders(self, announce: Callable[[str], Awaitable[None]]) -> None:
        """Announce timers and reminders while this app runs (chat and voice, not one-shot ask)."""
        scheduler = ReminderScheduler(self.services.reminders, self.bus, announce)
        self.background.append(asyncio.create_task(scheduler.run(), name="reminders"))

    async def aclose(self) -> None:
        for task in self.background:
            task.cancel()
        await asyncio.gather(*self.background, return_exceptions=True)
        await self.services.aclose()
        await self.llm.aclose()
        self.db.close()


def build_app(
    settings: Settings,
    channel: UserChannel,
    *,
    llm: ChatModel | None = None,
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
    llm = llm or LLMClient(settings.llm.active())
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
    )
    return App(settings, db, audit, history, bus, registry, llm, services, agent)
