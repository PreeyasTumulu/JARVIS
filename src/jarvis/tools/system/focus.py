"""Focus sessions: Jarvis keeps reminders to itself for a while, then says what you missed.

A timer still rings (it is usually the pasta), and answering a command still works. Reminders
that fall due stay pending, so they survive a restart and are announced as missed when the
session ends. Windows offers no supported way to turn on Do Not Disturb, so other apps' pop-ups
and sounds are not touched (ADR-078, RISKS.md R57).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.platform.notifications import NotificationAccessError
from jarvis.storage.repositories import Preferences
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.notifications.store import Notifications
from jarvis.tools.registry import tool
from jarvis.tools.system.reminders import Reminders, duration_words

log = logging.getLogger(__name__)

KEY = "focus.session"
MAX_MINUTES = 480
SHOW_NAMES = 3


@dataclass(frozen=True)
class Session:
    started_at: float
    ends_at: float
    label: str = ""


class Focus:
    """The session, kept in the preferences so that a restart does not lose it."""

    def __init__(
        self,
        reminders: Reminders,
        notifications: Notifications,
        prefs: Preferences,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._reminders = reminders
        self._notifications = notifications
        self._prefs = prefs
        self._clock = clock or reminders.clock
        self._changed = asyncio.Event()
        saved: dict[str, Any] | None = prefs.get(KEY)
        self.session = Session(**saved) if saved else None
        self._apply()

    def _apply(self) -> None:
        self._reminders.quiet = self.session is not None
        self._reminders.changed.set()
        self._changed.set()

    def start(self, minutes: float, label: str = "") -> Session:
        now = self._clock()
        self.session = Session(now, now + minutes * 60, label)
        self._prefs.set(KEY, vars(self.session))
        self._apply()
        return self.session

    async def finish(self) -> str:
        """End the session and say how it went: counts and senders, never the words."""
        session = self.session
        if session is None:
            return ""
        now = self._clock()
        held = [r for r in self._reminders.pending() if r.kind == "reminder" and r.due_at <= now]
        names = await self._senders(session)
        self.session = None
        self._prefs.set(KEY, None)
        self._apply()
        took = max(1.0, min(now, session.ends_at) - session.started_at)
        parts = [f"Your focus session is over, after {duration_words(took)}."]
        if names:
            noun = "message" if len(names) == 1 else "messages"
            shown = ", ".join(dict.fromkeys(names[:SHOW_NAMES]))
            parts.append(f"{len(names)} new {noun} came in, from {shown}.")
        if held:
            noun = "reminder" if len(held) == 1 else "reminders"
            parts.append(f"{len(held)} {noun} waited.")
        return " ".join(parts)

    async def _senders(self, session: Session) -> list[str]:
        with contextlib.suppress(NotificationAccessError):
            await self._notifications.refresh()
        start = datetime.fromtimestamp(session.started_at, UTC)
        return [
            item.title or item.app
            for item in self._notifications.store.recent(include_read=False)
            if item.created >= start
        ]

    async def run(self, announce: Callable[[str], Awaitable[None]]) -> None:
        """End a session when its time is up, even one that ran out while Jarvis was off."""
        while True:
            self._changed.clear()
            session = self.session
            delay = None if session is None else session.ends_at - self._clock()
            if delay is not None and delay <= 0:
                try:
                    await announce(await self.finish())
                except Exception:
                    log.exception("Ending the focus session failed")
                continue
            with contextlib.suppress(TimeoutError):
                await asyncio.wait_for(self._changed.wait(), timeout=delay)


def _focus(ctx: ToolContext) -> Focus:
    focus = ctx.services.focus
    if focus is None:
        raise ToolError("Focus sessions are not available here.")
    return focus


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def focus_start(
    ctx: ToolContext, minutes: float = 25, label: str | None = None
) -> ToolResult:
    """Start a focus session: Jarvis holds its reminders until the end, then says what was missed.
    For "start a focus session for 50 minutes" or "pomodoro".

    Args:
        minutes: How long, for example 25.
        label: Optional name for what the user is working on.
    """
    focus = _focus(ctx)
    if not 1 <= minutes <= MAX_MINUTES:
        raise ToolError(f"A focus session can run from 1 to {MAX_MINUTES} minutes.")
    if focus.session is not None:
        left = focus.session.ends_at - ctx.services.reminders.clock()
        raise ToolError(f"A focus session is already running, with {duration_words(left)} left.")
    focus.start(minutes, " ".join((label or "").split()))
    return ToolResult.success(
        data={"minutes": minutes},
        speech=f"Focus session started for {duration_words(minutes * 60)}. I'll hold reminders.",
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def focus_end(ctx: ToolContext) -> ToolResult:
    """End the focus session now and hear what was missed."""
    focus = _focus(ctx)
    if focus.session is None:
        raise ToolError("No focus session is running.")
    return ToolResult.success(data={"ended": True}, speech=await focus.finish())


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def focus_status(ctx: ToolContext) -> ToolResult:
    """Say whether a focus session is running and how long is left."""
    session = _focus(ctx).session
    if session is None:
        return ToolResult.success(data={"running": False}, speech="No focus session is running.")
    left = max(1.0, session.ends_at - ctx.services.reminders.clock())
    return ToolResult.success(
        data={"running": True, "seconds_left": round(left), "label": session.label},
        speech=f"{duration_words(left)} left in your focus session.",
    )
