"""The morning briefing: weather, today's calendar and reminders, unread email and messages
(ADR-066).

Each part reuses the tool or service that already does it, runs with its own timeout, and is
left out quietly when it is not set up or fails, so one broken part never spoils the rest.
Email and messages are counts and senders only: no subject lines or message text are read
out unless you ask for them afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

PART_TIMEOUT_S = 20
PARTS = ("weather", "calendar", "reminders", "mail", "messages")


def greeting(now: datetime) -> str:
    if now.hour < 12:
        return "Good morning."
    if now.hour < 17:
        return "Good afternoon."
    return "Good evening."


def _names(names: list[str], limit: int = 3) -> str:
    unique = list(dict.fromkeys(n for n in names if n))
    shown = unique[:limit]
    if len(unique) > limit:
        shown.append(f"{len(unique) - limit} more")
    if len(shown) <= 1:
        return "".join(shown)
    return ", ".join(shown[:-1]) + " and " + shown[-1]


async def _weather(ctx: ToolContext) -> str | None:
    from jarvis.tools.data.weather import weather

    if not ctx.settings.weather.home.strip():
        return None  # no home city set: nothing to say without asking
    result = await weather.fn(ctx, place=None, day="today")
    return result.speech


async def _calendar(ctx: ToolContext) -> str | None:
    from jarvis.tools.calendar.tools import calendar_events

    result = await calendar_events.fn(ctx, day="today")
    return result.speech


async def _reminders(ctx: ToolContext) -> str | None:
    now = datetime.now().astimezone()
    end = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    due = [r for r in ctx.services.reminders.pending() if r.due.astimezone() < end]
    if not due:
        return None
    items = [f"{r.message} at {r.due.astimezone().strftime('%I:%M %p').lstrip('0')}" for r in due]
    noun = "reminder" if len(due) == 1 else "reminders"
    return f"{len(due)} {noun} today: {'; '.join(items[:3])}."


async def _mail(ctx: ToolContext) -> str | None:
    mailbox = ctx.services.mail
    unread = await mailbox.count(unread_only=True)
    if not unread:
        return "No unread email."
    newest = await mailbox.recent(unread_only=True, names=None, limit=5)
    noun = "email" if unread == 1 else "emails"
    return f"{unread} unread {noun}, from {_names([h.who for h in newest])}."


async def _messages(ctx: ToolContext) -> str | None:
    notifications = ctx.services.notifications
    await notifications.refresh()
    new = notifications.store.recent(include_read=False)
    if not new:
        return None
    noun = "message" if len(new) == 1 else "messages"
    return f"{len(new)} new {noun}, from {_names([n.title or n.app for n in new])}."


SOURCES: dict[str, Callable[[ToolContext], Awaitable[str | None]]] = {
    "weather": _weather,
    "calendar": _calendar,
    "reminders": _reminders,
    "mail": _mail,
    "messages": _messages,
}


async def _part(name: str, ctx: ToolContext) -> tuple[str, str | None]:
    try:
        async with asyncio.timeout(PART_TIMEOUT_S):
            return name, await SOURCES[name](ctx)
    except ToolError as exc:
        log.info("Briefing: %s skipped (%s)", name, exc)
    except Exception as exc:  # a part that is not set up or broken is left out
        log.info("Briefing: %s skipped (%s)", name, exc)
    return name, None


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=60)
async def briefing(ctx: ToolContext) -> ToolResult:
    """The user's briefing for the day: weather, today's calendar and reminders, and unread
    email and messages, for "good morning", "brief me", or "how does my day look"."""
    wanted = [p for p in ctx.settings.briefing.parts if p in SOURCES]
    results = dict(await asyncio.gather(*(_part(name, ctx) for name in wanted)))
    said = [results[name] for name in wanted if results.get(name)]
    now = datetime.now().astimezone()
    if not said:
        speech = (
            f"{greeting(now)} I have nothing to brief you on yet: set your home city, calendar, "
            "or email (SETUP.md 5k)."
        )
    else:
        speech = " ".join([greeting(now), *[s for s in said if s]])
    return ToolResult.success(
        data={name: results.get(name) for name in wanted},
        speech=speech,
        hint="Say the summary as it is.",
    )
