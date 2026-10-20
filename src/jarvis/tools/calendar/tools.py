"""calendar_events: "what's on today", "am I free tomorrow", "my next meeting".

Private and untrusted: event titles and places come from invitations other people wrote.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.calendar.feed import CalendarError, Event, day_range
from jarvis.tools.registry import tool


def _item(event: Event, now: datetime) -> dict[str, Any]:
    item: dict[str, Any] = {
        "title": event.title,
        "day": event.start.strftime("%A %d %B"),
        "time": event.spoken_time(),
    }
    if not event.all_day:
        item["ends"] = event.end.strftime("%I:%M %p").lstrip("0")
        item["now"] = event.start <= now < event.end
    if event.location:
        item["where"] = event.location
    return item


def _spoken(events: list[Event], label: str, now: datetime) -> str:
    if label == "next":
        if not events:
            return "Nothing on your calendar in the next two weeks."
        first = events[0]
        when = "today" if first.start.date() == now.date() else first.start.strftime("%A")
        if first.start <= now < first.end and not first.all_day:
            return f"You're in {first.title} now, until {_clock(first.end)}."
        at = "" if first.all_day else f" at {first.spoken_time()}"
        return f"Next is {first.title}, {when}{at}."
    if not events:
        return f"Nothing on your calendar {label}."
    count = len(events)
    days = {e.start.date() for e in events}
    named = []
    for event in events[:3]:
        day = f" {event.start.strftime('%A')}" if len(days) > 1 else ""
        at = " all day" if event.all_day else f" at {event.spoken_time()}"
        named.append(f"{event.title}{day}{at}")
    more = f", and {count - 3} more" if count > 3 else ""
    noun = "event" if count == 1 else "events"
    return f"You have {count} {noun} {label}: {', '.join(named)}{more}."


def _clock(moment: datetime) -> str:
    return moment.strftime("%I:%M %p").lstrip("0").replace(":00 ", " ")


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=30)
async def calendar_events(ctx: ToolContext, day: str = "today") -> ToolResult:
    """The user's calendar: events on a day or in a week, or the next one, for "what's on
    today", "am I free tomorrow afternoon", "my meetings on Friday", or "what's my next
    meeting".

    Args:
        day: today, tomorrow, a weekday such as friday, this week, next week, a date as
            YYYY-MM-DD, or next for the next upcoming event.
    """
    now = datetime.now().astimezone()
    try:
        start, end, label = day_range(day, now)
        events = await ctx.services.calendar.events(start, end)
    except CalendarError as exc:
        raise ToolError(str(exc)) from exc
    if label == "next":
        events = [e for e in events if e.end > now and not e.all_day][:1] or [
            e for e in events if e.end > now
        ][:1]
    shown = events[: ctx.settings.calendar.max_events]
    return ToolResult.success(
        data={"when": label, "events": [_item(e, now) for e in shown], "total": len(events)},
        speech=_spoken(events, label, now),
    )
