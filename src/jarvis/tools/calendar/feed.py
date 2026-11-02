"""Your calendar from its private iCal address, read-only (ADR-057).

Google Calendar (and Outlook) publish a secret iCal link per calendar. Jarvis downloads it at
most every `calendar.cache_s` seconds, keeps it in memory only, and expands repeating events
with recurring-ical-events, so "standup every weekday" shows up on the right days. Times are
turned into this laptop's time zone.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any

import httpx

from jarvis.config import CalendarSettings

log = logging.getLogger(__name__)

URL_ENV = "CALENDAR_ICS_URL"  # one or more secret iCal links, separated by spaces or commas
NEXT_DAYS = 14  # how far "my next meeting" looks
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class CalendarError(Exception):
    """Something to tell the user (not set up, the link is wrong, offline)."""


@dataclass(frozen=True)
class Event:
    title: str
    start: datetime
    end: datetime
    all_day: bool
    location: str = ""

    def spoken_time(self) -> str:
        if self.all_day:
            return "all day"
        return self.start.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


def day_range(day: str, now: datetime) -> tuple[datetime, datetime, str]:
    """(start, end, label) for "today", "tomorrow", "friday", "this week", "next week",
    "2026-10-22", or "next" (the coming two weeks, for the next event)."""
    words = " ".join(day.casefold().replace("'s", "").split()) or "today"
    words = (
        words.removeprefix("on ").removeprefix("this ").strip() if words != "this week" else words
    )
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if words in ("today", "tonight", "now"):
        return midnight, midnight + timedelta(days=1), "today"
    if words == "tomorrow":
        return midnight + timedelta(days=1), midnight + timedelta(days=2), "tomorrow"
    if words in ("next", "upcoming", "soon"):
        return now, now + timedelta(days=NEXT_DAYS), "next"
    if words in ("this week", "week", "the week"):
        start = midnight - timedelta(days=midnight.weekday())
        return now, start + timedelta(days=7), "this week"
    if words == "next week":
        start = midnight - timedelta(days=midnight.weekday()) + timedelta(days=7)
        return start, start + timedelta(days=7), "next week"
    name = words.removeprefix("next ").strip()
    if name in WEEKDAYS:
        ahead = (WEEKDAYS.index(name) - midnight.weekday()) % 7
        if words.startswith("next ") and ahead == 0:
            ahead = 7
        start = midnight + timedelta(days=ahead)
        return start, start + timedelta(days=1), f"on {name.capitalize()}"
    if _ISO.match(words):
        start = datetime.combine(date.fromisoformat(words), datetime.min.time(), now.tzinfo)
        return start, start + timedelta(days=1), f"on {start.strftime('%A %d %B')}"
    raise CalendarError(
        f"I don't know which day '{day}' is. Say today, tomorrow, a weekday, or a date."
    )


def _as_local(value: Any, tz: Any) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        moment = value if value.tzinfo else value.replace(tzinfo=tz)
        return moment.astimezone(tz), False
    return datetime.combine(value, datetime.min.time(), tz), True  # an all-day date


def parse_events(ics: bytes, start: datetime, end: datetime) -> list[Event]:
    """Events (repeats expanded) overlapping [start, end), sorted by start."""
    import icalendar
    import recurring_ical_events

    tz = start.tzinfo
    try:
        calendar = icalendar.Calendar.from_ical(ics)
    except ValueError as exc:
        raise CalendarError("The calendar link did not return a calendar.") from exc
    found = []
    for component in recurring_ical_events.of(calendar).between(start, end):
        if str(component.get("STATUS", "")).upper() == "CANCELLED":
            continue
        begin = component.get("DTSTART")
        if begin is None:
            continue
        first, all_day = _as_local(begin.dt, tz)
        finish = component.get("DTEND")
        last = _as_local(finish.dt, tz)[0] if finish is not None else first
        found.append(
            Event(
                title=" ".join(str(component.get("SUMMARY", "")).split()) or "(no title)",
                start=first,
                end=last,
                all_day=all_day,
                location=" ".join(str(component.get("LOCATION", "")).split()),
            )
        )
    found.sort(key=lambda e: (not e.all_day, e.start))
    return found


class Calendar:
    def __init__(
        self,
        settings: CalendarSettings,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
        urls: list[str] | None = None,
    ) -> None:
        self._cfg = settings
        self._http = http
        self._clock = clock
        self._urls = urls
        self._cached: list[bytes] = []
        self._fetched = float("-inf")
        self._lock = asyncio.Lock()

    @staticmethod
    def urls() -> list[str]:
        return [u for u in re.split(r"[\s,]+", os.environ.get(URL_ENV, "")) if u]

    async def _feeds(self) -> list[bytes]:
        urls = self._urls if self._urls is not None else self.urls()
        if not urls:
            raise CalendarError(
                "Your calendar isn't set up yet. Put its secret iCal address in .env as "
                f"{URL_ENV} (SETUP.md 5k)."
            )
        async with self._lock:
            if self._cached and self._clock() - self._fetched < self._cfg.cache_s:
                return self._cached
            http = self._http or httpx.AsyncClient(timeout=self._cfg.timeout_s)
            try:
                feeds = []
                for url in urls:
                    response = await http.get(url, follow_redirects=True)
                    if response.status_code != 200:
                        raise CalendarError(
                            f"The calendar link answered {response.status_code}; it may have "
                            "been reset. Copy the secret iCal address again."
                        )
                    feeds.append(response.content)
            except httpx.HTTPError as exc:
                raise CalendarError(f"I couldn't download the calendar ({exc}).") from exc
            finally:
                if self._http is None:
                    await http.aclose()
            self._cached, self._fetched = feeds, self._clock()
            return feeds

    async def events(self, start: datetime, end: datetime) -> list[Event]:
        feeds = await self._feeds()
        found: list[Event] = []
        for feed in feeds:
            found += await asyncio.to_thread(parse_events, feed, start, end)
        found.sort(key=lambda e: (not e.all_day, e.start))
        return found
