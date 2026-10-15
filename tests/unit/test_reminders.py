"""Timers and reminders: time parsing, the tools, and the scheduler that announces them."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime
from typing import Any

import pytest

from jarvis.core.events import EventBus, ReminderDue
from jarvis.storage.db import Database
from jarvis.tools.base import ToolError
from jarvis.tools.system.reminders import (
    Reminders,
    ReminderScheduler,
    clock_time,
    duration_words,
    parse_at,
    spoken_when,
)
from tests.conftest import FakeChannel, Harness, MakeApp, reply

NOW = datetime(2026, 10, 15, 14, 0)  # a Thursday afternoon


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("17:30", datetime(2026, 10, 15, 17, 30)),
        ("5:30 pm", datetime(2026, 10, 15, 17, 30)),
        ("5:30 p.m.", datetime(2026, 10, 15, 17, 30)),
        ("5pm", datetime(2026, 10, 15, 17, 0)),
        ("5:30", datetime(2026, 10, 15, 17, 30)),  # the next 5:30 to come
        ("1:15", datetime(2026, 10, 16, 1, 15)),
        ("9 am", datetime(2026, 10, 16, 9, 0)),  # already passed today
        ("tomorrow 9 am", datetime(2026, 10, 16, 9, 0)),
        ("8 tonight", datetime(2026, 10, 15, 20, 0)),
        ("noon", datetime(2026, 10, 16, 12, 0)),
        ("2026-10-17 10:15", datetime(2026, 10, 17, 10, 15)),
        ("2026-10-17", datetime(2026, 10, 17, 9, 0)),
    ],
)
def test_parse_at(text: str, expected: datetime) -> None:
    assert parse_at(text, NOW) == expected


@pytest.mark.parametrize("text", ["soonish", "25:00", "13 pm", "today 9 am"])
def test_parse_at_rejects(text: str) -> None:
    with pytest.raises(ToolError):
        parse_at(text, NOW)


def test_spoken_times() -> None:
    assert clock_time(datetime(2026, 10, 15, 9, 0)) == "9 AM"
    assert clock_time(datetime(2026, 10, 15, 15, 5)) == "3:05 PM"
    assert clock_time(datetime(2026, 10, 15, 0, 30)) == "12:30 AM"
    assert spoken_when(datetime(2026, 10, 16, 9, 0), NOW) == "tomorrow at 9 AM"
    assert spoken_when(datetime(2026, 10, 19, 9, 0), NOW) == "Monday at 9 AM"
    assert spoken_when(datetime(2026, 11, 2, 9, 0), NOW) == "2 November at 9 AM"
    assert duration_words(90) == "1 minute 30 seconds"
    assert duration_words(7200) == "2 hours"


def spoken(h: Harness) -> str:
    message = [m for m in h.app.agent.messages if m["role"] == "tool"][-1]
    payload: dict[str, Any] = json.loads(message["content"])
    return str(payload.get("summary") or payload.get("error"))


async def test_set_timer_and_reminder(make_app: MakeApp) -> None:
    h = make_app(
        [
            reply("", ("set_timer", {"minutes": 5, "label": "timer"})),
            reply("", ("set_reminder", {"message": "to stretch", "in_minutes": 10})),
            reply("ok"),
        ]
    )
    await h.app.agent.run_turn("set a timer for 5 minutes and remind me in 10 minutes to stretch")
    pending = h.app.services.reminders.pending()
    assert [(r.kind, r.message) for r in pending] == [
        ("timer", "5 minutes"),
        ("reminder", "stretch"),
    ]
    assert spoken(h).startswith("Reminder set for ")
    assert spoken(h).endswith(": stretch. Keep Jarvis running to hear it.")


async def test_reminder_needs_a_time(make_app: MakeApp) -> None:
    h = make_app([reply("", ("set_reminder", {"message": "stretch"})), reply("When?")])
    await h.app.agent.run_turn("remind me to stretch")
    assert "in how many minutes, or at what time" in h.audit()[0]["error"]


async def test_cancel_one_is_safe_but_all_asks(make_app: MakeApp) -> None:
    channel = FakeChannel(confirm=False)
    h = make_app(channel=channel)
    reminders = h.app.services.reminders
    now = reminders.clock()
    reminders.add("reminder", "stretch", now + 600)
    reminders.add("reminder", "call mom", now + 1200)
    reminders.add("timer", "pasta", now + 300)
    h.llm._script.extend(
        [
            reply("", ("cancel_reminder", {"which": "the stretch one"})),
            reply("", ("cancel_reminder", {"which": "all"})),
            reply("ok"),
        ]
    )
    await h.app.agent.run_turn("cancel the stretch reminder, then all of them")
    one, every = h.audit()
    assert one["decision"] == "auto"
    assert json.loads(one["args_json"]) == {"which": "id:1"}
    assert every["decision"] == "denied"
    assert channel.requests[0].summary == "Cancel 2 timers and reminders (pasta, call mom)"
    assert [r.message for r in reminders.pending()] == ["pasta", "call mom"]


async def test_list_reminders(make_app: MakeApp) -> None:
    h = make_app([reply("", ("list_reminders", {})), reply("ok")])
    reminders = h.app.services.reminders
    reminders.add("timer", "pasta", reminders.clock() + 300)
    await h.app.agent.run_turn("what reminders do I have")
    assert spoken(h).startswith("One timer: pasta, ")


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 15, 14, 0).timestamp()

    def __call__(self) -> float:
        return self.now


async def test_scheduler_announces_due_and_missed_reminders() -> None:
    clock = Clock()
    reminders = Reminders(Database(":memory:"), clock=clock)
    reminders.add("reminder", "very old", clock.now - 2 * 24 * 3600)
    reminders.add("reminder", "call mom", clock.now - 600)
    bus = EventBus()
    events: list[Any] = []
    bus.subscribe(events.append)
    said: list[str] = []

    async def announce(text: str) -> None:
        said.append(text)

    task = asyncio.create_task(ReminderScheduler(reminders, bus, announce).run())
    try:
        await asyncio.sleep(0.05)
        assert reminders.running
        assert said == ["You missed a reminder at 1:50 PM: call mom."]

        reminders.add("timer", "pasta", clock.now)  # due now: wakes the scheduler at once
        async with asyncio.timeout(2):
            while len(said) < 2:  # noqa: ASYNC110
                await asyncio.sleep(0.01)
        assert said[1] == "Timer done: pasta."
        assert [e.text for e in events if isinstance(e, ReminderDue)] == said
        assert reminders.pending() == []
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    assert not reminders.running
