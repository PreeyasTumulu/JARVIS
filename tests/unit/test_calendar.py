"""Calendar: day ranges, iCal parsing with repeats, and calendar_events. The feed is faked."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from jarvis.config import CalendarSettings
from jarvis.tools.calendar.feed import Calendar, CalendarError, day_range, parse_events
from tests.conftest import CALENDAR_URL, FakeWeb, MakeApp

NOW = datetime(2026, 10, 21, 9, 30).astimezone()  # a Wednesday


def utc(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y%m%dT%H%M%SZ")


def ics(*events: str) -> bytes:
    body = "\r\n".join(events)
    return (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\nPRODID:-//test//EN\r\n" + body + "\r\nEND:VCALENDAR\r\n"
    ).encode()


def event(uid: str, title: str, start: datetime, end: datetime, *extra: str) -> str:
    lines = [
        "BEGIN:VEVENT",
        f"UID:{uid}",
        f"SUMMARY:{title}",
        f"DTSTART:{utc(start)}",
        f"DTEND:{utc(end)}",
        *extra,
        "END:VEVENT",
    ]
    return "\r\n".join(lines)


def all_day(uid: str, title: str, day: datetime) -> str:
    return "\r\n".join(
        [
            "BEGIN:VEVENT",
            f"UID:{uid}",
            f"SUMMARY:{title}",
            f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}",
            f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}",
            "END:VEVENT",
        ]
    )


def at(day_offset: int, hour: int, minute: int = 0) -> datetime:
    today = datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
    return today + timedelta(days=day_offset, hours=hour, minutes=minute)


def week_feed() -> bytes:
    return ics(
        event("s", "Standup", at(-3, 10), at(-3, 10, 15), "RRULE:FREQ=DAILY"),
        event("l", "Lunch with Ravi", at(0, 13), at(0, 14), "LOCATION:Cafe Nilofer"),
        event("c", "Cancelled sync", at(0, 15), at(0, 16), "STATUS:CANCELLED"),
        all_day("d", "Diwali", at(1, 0)),
        event("r", "Dentist", at(3, 17), at(3, 18)),
    )


@pytest.mark.parametrize(
    ("day", "start", "days", "label"),
    [
        ("today", "2026-10-21", 1, "today"),
        ("Tomorrow", "2026-10-22", 1, "tomorrow"),
        ("friday", "2026-10-23", 1, "on Friday"),
        ("on Friday", "2026-10-23", 1, "on Friday"),
        ("wednesday", "2026-10-21", 1, "on Wednesday"),
        ("next wednesday", "2026-10-28", 1, "on Wednesday"),
        ("next week", "2026-10-26", 7, "next week"),
        ("2026-12-25", "2026-12-25", 1, "on Friday 25 December"),
    ],
)
def test_day_range(day: str, start: str, days: int, label: str) -> None:
    first, last, said = day_range(day, NOW)
    assert first.date().isoformat() == start
    assert (last - first) == timedelta(days=days)
    assert said == label


def test_this_week_starts_now_and_next_looks_two_weeks() -> None:
    first, last, _ = day_range("this week", NOW)
    assert first == NOW
    assert last.date().isoformat() == "2026-10-26"
    first, last, _ = day_range("next", NOW)
    assert (first, last - first) == (NOW, timedelta(days=14))


def test_unknown_day() -> None:
    with pytest.raises(CalendarError, match="don't know which day"):
        day_range("the day after the party", NOW)


def test_parse_expands_repeats_and_skips_cancelled() -> None:
    start, end = at(0, 0), at(1, 0)
    found = parse_events(week_feed(), start, end)
    assert [(e.title, e.start.hour) for e in found] == [("Standup", 10), ("Lunch with Ravi", 13)]
    assert found[1].location == "Cafe Nilofer"
    tomorrow = parse_events(week_feed(), at(1, 0), at(2, 0))
    assert [(e.title, e.all_day) for e in tomorrow] == [("Diwali", True), ("Standup", False)]


def test_a_broken_feed() -> None:
    with pytest.raises(CalendarError, match="did not return a calendar"):
        parse_events(b"<html>not a calendar</html>", at(0, 0), at(1, 0))


async def call(h: Any, **args: Any) -> Any:
    from jarvis.llm.types import ToolCall
    from jarvis.tools.base import ToolContext

    ctx = ToolContext(
        settings=h.app.settings,
        channel=h.channel,
        services=h.app.services,
        session_id="s",
        turn_id="t",
    )
    tool_call = ToolCall("c1", "calendar_events", json.dumps(args))
    return await h.app.agent._executor.run(tool_call, ctx)


async def test_todays_events(make_app: MakeApp, web: FakeWeb) -> None:
    web.route("calendar.test/private", content=week_feed())
    outcome = await call(make_app(), day="today")
    result = outcome.result
    assert result.speech == "You have 2 events today: Standup at 10 AM, Lunch with Ravi at 1 PM."
    assert result.data["events"][1]["where"] == "Cafe Nilofer"
    assert outcome.flags.private
    assert outcome.flags.untrusted


async def test_tomorrow_has_an_all_day_event(make_app: MakeApp, web: FakeWeb) -> None:
    web.route("calendar.test/private", content=week_feed())
    result = (await call(make_app(), day="tomorrow")).result
    assert result.speech == "You have 2 events tomorrow: Diwali all day, Standup at 10 AM."


async def test_the_next_event(make_app: MakeApp, web: FakeWeb) -> None:
    soon = datetime.now().astimezone().replace(second=0, microsecond=0) + timedelta(hours=2)
    web.route(
        "calendar.test/private",
        content=ics(
            event("a", "Call with Sita", soon, soon + timedelta(minutes=30)),
            event("b", "Review", soon + timedelta(days=1), soon + timedelta(days=1, hours=1)),
        ),
    )
    result = (await call(make_app(), day="next")).result
    assert result.speech.startswith("Next is Call with Sita, ")
    assert len(result.data["events"]) == 1


async def test_nothing_on(make_app: MakeApp, web: FakeWeb) -> None:
    web.route("calendar.test/private", content=ics())
    result = (await call(make_app(), day="friday")).result
    assert result.speech == "Nothing on your calendar on Friday."


async def test_a_reset_link_is_explained(make_app: MakeApp, web: FakeWeb) -> None:
    web.route("calendar.test/private", status=404)
    outcome = await call(make_app())
    assert "answered 404" in outcome.result.error


async def test_the_feed_is_cached(web: FakeWeb) -> None:
    import httpx

    web.route("calendar.test/private", content=week_feed())
    clock = [0.0]
    calendar = Calendar(
        CalendarSettings(cache_s=300),
        http=httpx.AsyncClient(transport=httpx.MockTransport(web.handle)),
        clock=lambda: clock[0],
        urls=[CALENDAR_URL],
    )
    await calendar.events(at(0, 0), at(1, 0))
    await calendar.events(at(1, 0), at(2, 0))
    assert web.hits("calendar.test/private") == 1
    clock[0] = 301
    await calendar.events(at(0, 0), at(1, 0))
    assert web.hits("calendar.test/private") == 2


async def test_calendar_not_set_up(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CALENDAR_ICS_URL", raising=False)
    with pytest.raises(CalendarError, match="isn't set up"):
        await Calendar(CalendarSettings()).events(at(0, 0), at(1, 0))
