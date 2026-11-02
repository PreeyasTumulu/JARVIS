"""Timers and reminders, stored in SQLite and announced by a scheduler while Jarvis runs.

`jarvis chat` and `jarvis voice` run the scheduler. A reminder that falls due while Jarvis is not
running is announced as missed the next time it starts, if it is less than a day late; older ones
are marked missed quietly.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from datetime import time as clock
from typing import Any

from rapidfuzz import fuzz

from jarvis.core.events import EventBus, ReminderDue
from jarvis.storage.db import Database
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

MISSED_AFTER_S = 120  # announced as missed when later than this
DROP_AFTER_S = 24 * 3600  # marked missed without a word when later than this
MAX_SLEEP_S = 30.0  # the scheduler re-checks the wall clock at least this often (sleep, DST)
MAX_TIMER_S = 24 * 3600
MATCH_SCORE = 80

_CLOCK = re.compile(
    r"^(?:(?P<day1>today|tonight|tomorrow)\s+)?(?:at\s+)?(?P<hour>\d{1,2})(?::(?P<minute>\d{2}))?"
    r"\s*(?P<ampm>am|pm)?(?:\s+(?P<day2>today|tonight|tomorrow))?$"
)
_ALL = {"all", "everything", "all of them", "all reminders", "all timers", "everything pending"}
_LAST = {"last", "latest", "newest", "last one", "most recent"}
_NEXT = {"next", "next one", "soonest"}
_GENERIC_LABELS = {"timer", "countdown", "alarm", "reminder"}


@dataclass(frozen=True)
class Reminder:
    id: int
    kind: str  # "timer" or "reminder"
    message: str
    due_at: float
    created_at: float

    @property
    def due(self) -> datetime:
        return datetime.fromtimestamp(self.due_at)

    def announcement(self, late_s: float) -> str:
        if late_s > MISSED_AFTER_S:
            return f"You missed a {self.kind} at {clock_time(self.due)}: {self.message}."
        if self.kind == "timer":
            return f"Timer done: {self.message}."
        return f"Reminder: {self.message}."


def clock_time(moment: datetime) -> str:
    """ "3:05 PM", or "9 AM" on the hour."""
    hour = moment.hour % 12 or 12
    suffix = "AM" if moment.hour < 12 else "PM"
    return f"{hour} {suffix}" if moment.minute == 0 else f"{hour}:{moment.minute:02d} {suffix}"


def spoken_when(moment: datetime, now: datetime) -> str:
    days = (moment.date() - now.date()).days
    if days == 0:
        return clock_time(moment)
    if days == 1:
        return f"tomorrow at {clock_time(moment)}"
    if days < 7:
        return f"{moment:%A} at {clock_time(moment)}"
    return f"{moment.day} {moment:%B} at {clock_time(moment)}"


def duration_words(seconds: float) -> str:
    total = round(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    parts = [
        f"{count} {unit}{'' if count == 1 else 's'}"
        for count, unit in ((hours, "hour"), (minutes, "minute"), (secs, "second"))
        if count
    ]
    return " ".join(parts) or "0 seconds"


def parse_at(text: str, now: datetime) -> datetime:
    """A clock time ("17:30", "5:30 pm", "tomorrow 9 am") or ISO date and time, as local time.

    A time without am or pm, like "5:30", means the next 5:30 to come, morning or evening.
    """
    stripped = text.strip()
    try:
        moment = datetime.fromisoformat(stripped)
    except ValueError:
        pass
    else:
        if moment.tzinfo is not None:
            moment = moment.astimezone().replace(tzinfo=None)
        if len(stripped) == 10:  # a date alone means that morning
            moment = moment.replace(hour=9)
        return moment

    raw = " ".join(stripped.casefold().replace(".", "").split())
    raw = raw.replace("noon", "12 pm").replace("midnight", "12 am")
    raw = re.sub(r"(\d)(am|pm)\b", r"\1 \2", raw)
    match = _CLOCK.match(raw)
    if match is None:
        raise ToolError(f"I couldn't understand the time '{text}'. Use a time like 5:30 pm.")
    hour, minute = int(match["hour"]), int(match["minute"] or 0)
    ampm, day = match["ampm"], match["day1"] or match["day2"]
    if minute > 59 or hour > 23 or (ampm and not 1 <= hour <= 12):
        raise ToolError(f"'{text}' is not a valid time.")

    if ampm is None and day is None and 1 <= hour <= 12:
        hours = (hour % 12, hour % 12 + 12)
        options = [
            datetime.combine(now.date() + timedelta(days=d), clock(h, minute))
            for d in (0, 1)
            for h in hours
        ]
        return min(option for option in options if option > now)

    if ampm == "pm" and hour != 12:
        hour += 12
    elif ampm == "am" and hour == 12:
        hour = 0
    elif ampm is None and day == "tonight" and hour < 12:
        hour += 12
    moment = datetime.combine(now.date(), clock(hour, minute))
    if day == "tomorrow":
        moment += timedelta(days=1)
    if moment <= now:
        if day in ("today", "tonight"):
            raise ToolError(f"{clock_time(moment)} has already passed today.")
        moment += timedelta(days=1)
    return moment


class ReminderStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, kind: str, message: str, due_at: float, now: float) -> Reminder:
        with self._db.transaction() as conn:
            cursor = conn.execute(
                "INSERT INTO reminders (kind, message, due_at, created_at) VALUES (?, ?, ?, ?)",
                (kind, message, due_at, now),
            )
            reminder_id = int(cursor.lastrowid or 0)
        return Reminder(reminder_id, kind, message, due_at, now)

    def pending(self) -> list[Reminder]:
        rows = self._db.execute(
            "SELECT id, kind, message, due_at, created_at FROM reminders "
            "WHERE status = 'pending' ORDER BY due_at"
        )
        return [Reminder(*tuple(row)) for row in rows]

    def finish(self, reminder_id: int, status: str, now: float) -> None:
        self._db.execute(
            "UPDATE reminders SET status = ?, fired_at = ? WHERE id = ?", (status, now, reminder_id)
        )


class Reminders:
    """What the tools use: the store, the clock, and a nudge that wakes the scheduler."""

    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self.store = ReminderStore(db)
        self.clock = clock
        self.changed = asyncio.Event()
        self.running = False  # true while a scheduler is announcing reminders

    def add(self, kind: str, message: str, due_at: float) -> Reminder:
        reminder = self.store.add(kind, message, due_at, self.clock())
        self.changed.set()
        return reminder

    def pending(self) -> list[Reminder]:
        return self.store.pending()

    def cancel(self, ids: list[int]) -> None:
        for reminder_id in ids:
            self.store.finish(reminder_id, "cancelled", self.clock())
        self.changed.set()


class ReminderScheduler:
    def __init__(
        self,
        reminders: Reminders,
        bus: EventBus,
        announce: Callable[[str], Awaitable[None]],
    ) -> None:
        self._reminders = reminders
        self._bus = bus
        self._announce = announce

    async def run(self) -> None:
        reminders = self._reminders
        reminders.running = True
        try:
            while True:
                reminders.changed.clear()  # before reading, so a new reminder is never missed
                now = reminders.clock()
                pending = reminders.pending()
                for item in pending:
                    if item.due_at <= now:
                        await self._fire(item, now)
                waits = [item.due_at - now for item in pending if item.due_at > now]
                delay = max(0.05, min([MAX_SLEEP_S, *waits]))
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(reminders.changed.wait(), timeout=delay)
        finally:
            reminders.running = False

    async def _fire(self, item: Reminder, now: float) -> None:
        late = now - item.due_at
        if late > DROP_AFTER_S:
            self._reminders.store.finish(item.id, "missed", now)
            return
        self._reminders.store.finish(item.id, "done", now)  # first, so it can never repeat
        text = item.announcement(late)
        log.info("%s %d is due", item.kind.capitalize(), item.id)
        await self._bus.publish(ReminderDue(reminder_id=item.id, kind=item.kind, text=text))
        try:
            await self._announce(text)
        except Exception:
            log.exception("Announcing %s %d failed", item.kind, item.id)


def match_reminders(pending: list[Reminder], which: str) -> list[Reminder]:
    text = " ".join(re.sub(r"\b(the|my|a|an|please)\b", " ", which.casefold()).split())
    if text.startswith("id:"):
        wanted = {int(part) for part in re.findall(r"\d+", text)}
        return [item for item in pending if item.id in wanted]
    if text in _ALL:
        kind = "timer" if "timer" in text else "reminder" if "reminder" in text else None
        return [item for item in pending if kind is None or item.kind == kind]
    if text in _LAST and pending:
        return [max(pending, key=lambda item: item.created_at)]
    if text in _NEXT and pending:
        return [min(pending, key=lambda item: item.due_at)]
    if text in ("timer", "timers", "reminder", "reminders"):
        return [item for item in pending if item.kind == text.rstrip("s")]
    return [
        item
        for item in pending
        if text and fuzz.partial_ratio(text, item.message.casefold()) >= MATCH_SCORE
    ]


def _not_running_note(ctx: ToolContext) -> str:
    if ctx.services.reminders.running:
        return ""
    return " Keep Jarvis running to hear it."


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def set_timer(
    ctx: ToolContext, minutes: float = 0, seconds: float = 0, label: str | None = None
) -> ToolResult:
    """Start a countdown timer that announces when it is done.

    Args:
        minutes: Minutes to count down, for example 5 or 1.5.
        seconds: Extra seconds, for example 30.
        label: Optional name for the timer, for example "pasta".
    """
    total = minutes * 60 + seconds
    if total < 1:
        raise ToolError("A timer needs a duration, for example 5 minutes.")
    if total > MAX_TIMER_S:
        raise ToolError("Timers can run for up to 24 hours. Use a reminder for later times.")
    reminders = ctx.services.reminders
    name = " ".join((label or "").split())
    generic = name.casefold().removeprefix("a ").removeprefix("the ") in _GENERIC_LABELS
    message = duration_words(total) if not name or generic else name
    item = reminders.add("timer", message, reminders.clock() + total)
    data = {"id": item.id, "seconds": round(total), "ends_at": clock_time(item.due)}
    speech = f"Timer set for {duration_words(total)}.{_not_running_note(ctx)}"
    return ToolResult.success(data=data, speech=speech)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def set_reminder(
    ctx: ToolContext, message: str, in_minutes: float | None = None, at: str | None = None
) -> ToolResult:
    """Remind the user about something later, after some minutes or at a clock time.

    Args:
        message: What to remind the user about, for example "stretch" or "call mom".
        in_minutes: Minutes from now, for "in 10 minutes" (2 hours is 120).
        at: A clock time or date and time, for example "17:30", "5:30 pm", or "2026-10-16 09:00".
    """
    reminders = ctx.services.reminders
    now = reminders.clock()
    if in_minutes is not None:
        if in_minutes <= 0:
            raise ToolError("The reminder time must be in the future.")
        due_at = now + in_minutes * 60
    elif at:
        due_at = parse_at(at, datetime.fromtimestamp(now)).timestamp()
    else:
        raise ToolError("Ask the user when: in how many minutes, or at what time.")
    text = re.sub(r"^(to|about)\s+", "", " ".join(message.split()), flags=re.I).rstrip(".")
    if not text:
        raise ToolError("Ask the user what the reminder is for.")
    item = reminders.add("reminder", text, due_at)
    when = spoken_when(item.due, datetime.fromtimestamp(now))
    data = {"id": item.id, "message": text, "due": when}
    speech = f"Reminder set for {when}: {text}.{_not_running_note(ctx)}"
    return ToolResult.success(data=data, speech=speech)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def list_reminders(ctx: ToolContext) -> ToolResult:
    """List the timers and reminders that have not gone off yet."""
    reminders = ctx.services.reminders
    pending = reminders.pending()
    now = datetime.fromtimestamp(reminders.clock())
    if not pending:
        return ToolResult.success(data=[], speech="You have no timers or reminders.")
    items: list[dict[str, Any]] = [
        {"kind": item.kind, "message": item.message, "due": spoken_when(item.due, now)}
        for item in pending
    ]
    first = items[0]
    if len(items) == 1:
        speech = f"One {first['kind']}: {first['message']}, {first['due']}."
    else:
        speech = (
            f"You have {len(items)} timers and reminders. "
            f"The next is {first['message']}, {first['due']}."
        )
    return ToolResult.success(data=items, speech=speech)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def cancel_reminder(ctx: ToolContext, which: str) -> ToolResult:
    """Cancel timers or reminders that have not gone off yet.

    Args:
        which: Words from the reminder such as "stretch", or "timer", "last", or "all".
    """
    reminders = ctx.services.reminders
    chosen = match_reminders(reminders.pending(), which)
    if not chosen:
        raise ToolError("That timer or reminder is no longer pending.")
    reminders.cancel([item.id for item in chosen])
    speech = "Cancelled." if len(chosen) == 1 else f"Cancelled {len(chosen)} of them."
    return ToolResult.success(data={"cancelled": [item.message for item in chosen]}, speech=speech)


@cancel_reminder.preparer
async def _prepare_cancel(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    pending = ctx.services.reminders.pending()
    if not pending:
        raise ToolError("There are no timers or reminders to cancel.")
    chosen = match_reminders(pending, args["which"])
    if not chosen:
        names = ", ".join(item.message for item in pending[:3])
        raise ToolError(
            f"No pending timer or reminder matches '{args['which']}'. Pending: {names}."
        )
    exact = {"which": "id:" + ",".join(str(item.id) for item in chosen)}  # what was confirmed
    if len(chosen) == 1:
        item = chosen[0]
        return Prepared(args=exact, summary=f"Cancel the {item.kind} '{item.message}'")
    names = ", ".join(item.message for item in chosen[:3])
    return Prepared(
        args=exact,
        summary=f"Cancel {len(chosen)} timers and reminders ({names})",
        risk=Risk.CONFIRM,
        reason="this cancels more than one",
    )
