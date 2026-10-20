"""Recall (past commands and memories by meaning) and the morning briefing. Embeddings, the
network, the mailbox, and the notification center are faked."""

from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any

import httpx
import pytest

from jarvis.core.meaning import Embedder, MeaningIndex
from jarvis.tools.recall import past_range, relevant_memories
from tests.conftest import (
    CALENDAR_URL,
    FakeMailServer,
    FakeNotificationCenter,
    FakeWeb,
    MakeApp,
    reply,
)
from tests.unit import test_data_tools as data

NOW = datetime(2026, 10, 21, 9, 30).astimezone()  # a Wednesday morning

# Meaning, faked: a text's vector counts its words from each topic.
TOPICS = {
    "docker": ("docker", "container", "containers", "postgres", "logs"),
    "work": ("manager", "boss", "report", "office"),
    "car": ("car", "drive", "swift"),
    "apps": ("open", "notepad", "weather"),
}


def vector(text: str) -> list[float]:
    words = text.casefold().replace("'", " ").split()
    return [float(sum(w in words for w in topic)) for topic in TOPICS.values()]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls = 0
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("ollama is not running", request=request)
        self.calls += 1
        texts = json.loads(request.content)["input"]
        return httpx.Response(
            200, json={"data": [{"embedding": vector(t.split(": ", 1)[1])} for t in texts]}
        )


@pytest.fixture
def embeddings() -> FakeEmbeddings:
    return FakeEmbeddings()


def with_meaning(h: Any, fake: FakeEmbeddings) -> None:
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    h.app.services.meaning = MeaningIndex(h.app.db, Embedder("http://x/v1", "nomic", http=http))


async def call(h: Any, tool: str, **args: Any) -> Any:
    from jarvis.llm.types import ToolCall
    from jarvis.tools.base import ToolContext

    ctx = ToolContext(
        settings=h.app.settings,
        channel=h.channel,
        services=h.app.services,
        session_id="s",
        turn_id="now",
    )
    return await h.app.agent._executor.run(ToolCall("c1", tool, json.dumps(args)), ctx)


def remember_commands(h: Any, *pairs: tuple[str, str]) -> None:
    for number, (said, answered) in enumerate(pairs):
        h.app.history.record(
            session_id="s",
            turn_id=f"t{number}",
            source="voice",
            input_text=said,
            response_text=answered,
            status="ok",
            model="m",
            iterations=1,
            latency_ms=1,
        )


# Time ranges


@pytest.mark.parametrize(
    ("when", "start", "label"),
    [
        ("today", "2026-10-21", "today"),
        ("yesterday", "2026-10-20", "yesterday"),
        ("this week", "2026-10-19", "this week"),
        ("last week", "2026-10-12", "last week"),
        ("last month", "2026-09-01", "last month"),
        ("monday", "2026-10-19", "on Monday"),
        ("on wednesday", "2026-10-14", "on Wednesday"),  # today is Wednesday: the one before
        ("3 days ago", "2026-10-18", "3 days ago"),
        ("2026-10-02", "2026-10-02", "on Friday 02 October"),
    ],
)
def test_past_ranges(when: str, start: str, label: str) -> None:
    first, _, said = past_range(when, NOW)
    assert first.date().isoformat() == start
    assert said == label


def test_anything_else_means_all_time() -> None:
    first, last, label = past_range("", NOW)
    assert (first.year, last, label) == (1, NOW, "ever")


# Recall


async def test_recall_by_meaning(make_app: MakeApp, embeddings: FakeEmbeddings) -> None:
    h = make_app()
    with_meaning(h, embeddings)
    remember_commands(
        h,
        ("what's the weather", "Sunny."),
        ("show the logs of the postgres container", "Postgres is running fine."),
        ("open notepad", "Done."),
    )
    outcome = await call(h, "recall", about="docker")
    assert outcome.result.data["found"][0]["you_said"] == "show the logs of the postgres container"
    assert outcome.result.speech.startswith("Today at ")
    assert outcome.flags.private
    assert outcome.flags.untrusted  # old answers can quote pages and messages


async def test_recall_indexes_each_command_once(
    make_app: MakeApp, embeddings: FakeEmbeddings
) -> None:
    h = make_app()
    with_meaning(h, embeddings)
    remember_commands(h, ("restart the docker container", "Done."))
    await call(h, "recall", about="docker")
    first = embeddings.calls
    await call(h, "recall", about="docker")
    assert embeddings.calls == first + 1  # only the question is embedded again


async def test_recall_falls_back_to_words(make_app: MakeApp, embeddings: FakeEmbeddings) -> None:
    h = make_app()
    with_meaning(h, embeddings)
    embeddings.down = True
    remember_commands(h, ("restart the docker container", "Done."), ("open notepad", "Done."))
    outcome = await call(h, "recall", about="docker")
    assert [f["you_said"] for f in outcome.result.data["found"]] == ["restart the docker container"]


async def test_recall_nothing_found(make_app: MakeApp) -> None:
    h = make_app()
    remember_commands(h, ("open notepad", "Done."))
    outcome = await call(h, "recall", about="taxes", when="today")
    assert not outcome.result.ok
    assert "nothing about taxes from today" in outcome.result.error
    empty = await call(h, "recall", about="taxes", when="last month")
    assert empty.result.speech == "I have no commands from last month."


# Memories by meaning


async def test_relevant_memories_by_meaning(make_app: MakeApp, embeddings: FakeEmbeddings) -> None:
    h = make_app()
    with_meaning(h, embeddings)
    h.app.services.memory.add("The user's manager is Ravi")
    h.app.services.memory.add("The user's car is a Swift")
    assert await relevant_memories(h.app.services, "who is my boss") == [
        "The user's manager is Ravi"
    ]
    assert await relevant_memories(h.app.services, "open notepad") == []


async def test_relevant_memories_without_embeddings_share_words(make_app: MakeApp) -> None:
    h = make_app()
    h.app.services.memory.add("The user's manager is Ravi")
    assert await relevant_memories(h.app.services, "who is my manager") == [
        "The user's manager is Ravi"
    ]


async def test_a_forgotten_memory_loses_its_vector(
    make_app: MakeApp, embeddings: FakeEmbeddings
) -> None:
    h = make_app()
    with_meaning(h, embeddings)
    memory = h.app.services.memory.add("The user's manager is Ravi")
    await relevant_memories(h.app.services, "boss")
    h.app.services.memory.remove([memory.id])
    await relevant_memories(h.app.services, "boss")
    assert h.app.db.execute("SELECT COUNT(*) FROM embeddings WHERE kind = 'memory'")[0][0] == 0


# The briefing


async def test_the_full_briefing(
    make_app: MakeApp,
    web: FakeWeb,
    mail_server: FakeMailServer,
    notification_center: FakeNotificationCenter,
) -> None:
    from tests.unit.test_calendar import at, event, ics

    web.route(data.GEOCODE, {"results": [data.HYDERABAD]})
    web.route(data.FORECAST, data.FORECAST_DATA)
    web.route("calendar.test/private", content=ics(event("s", "Standup", at(0, 10), at(0, 10, 15))))
    mail_server.add("Ravi Kumar", "ravi@x.example", "Secret merger plans", "details")
    mail_server.add("LinkedIn", "news@x.example", "Jobs", "jobs")
    notification_center.add("WhatsApp", "Amma", "Call me when you are free")
    h = make_app(overrides={"weather": {"home": "Hyderabad"}})
    h.app.services.reminders.add("reminder", "call the bank", time.time() + 60)
    outcome = await call(h, "briefing")
    speech = outcome.result.speech
    assert "In Hyderabad it's 27 degrees" in speech
    assert "You have 1 event today: Standup at 10 AM." in speech
    assert "1 reminder today: call the bank at" in speech
    assert "2 unread emails, from LinkedIn and Ravi Kumar." in speech
    assert "1 new message, from Amma." in speech
    assert "merger" not in speech  # counts and senders, never subjects
    assert "Call me" not in speech  # or message text
    assert notification_center.read  # notifications were checked
    assert not any(n.read for n in h.app.services.notifications.store.recent(include_read=True))


async def test_parts_that_are_not_set_up_are_left_out(make_app: MakeApp, web: FakeWeb) -> None:
    web.route("calendar.test/private", status=404)  # the calendar link fails
    h = make_app()  # no home city
    h.app.services.mail = type(h.app.services.mail)(h.app.settings.mail)  # mail not set up
    outcome = await call(h, "briefing")
    assert outcome.result.ok
    assert "nothing to brief you on" in outcome.result.speech


async def test_good_morning_runs_the_briefing_without_the_model(make_app: MakeApp) -> None:
    h = make_app()
    result = await h.app.agent.run_turn("Good morning, Jarvis")
    assert result.outcomes[0].call.name == "briefing"
    assert h.llm.requests == []


# The daily offer


def morning(h: Any, hour: int = 8) -> None:
    h.app.agent._clock = lambda: datetime(2026, 10, 21, hour, 0).astimezone()


async def test_the_briefing_is_offered_once_and_yes_plays_it(make_app: MakeApp) -> None:
    h = make_app(
        [reply("Notepad is open."), reply("Done.")], overrides={"briefing": {"offer": True}}
    )
    morning(h)
    first = await h.app.agent.run_turn("open notepad")
    assert first.text == "Notepad is open. By the way, would you like your morning briefing?"
    second = await h.app.agent.run_turn("yes please")
    assert second.outcomes[0].call.name == "briefing"
    assert len(h.llm.requests) == 1  # the yes never reached the model
    third = await h.app.agent.run_turn("open paint")
    assert "briefing" not in third.text  # once a day


async def test_no_to_the_offer_is_just_a_command(make_app: MakeApp) -> None:
    h = make_app(
        [reply("Notepad is open."), reply("Okay.")], overrides={"briefing": {"offer": True}}
    )
    morning(h)
    await h.app.agent.run_turn("open notepad")
    second = await h.app.agent.run_turn("no thanks")
    assert second.outcomes == []
    assert len(h.llm.requests) == 2


async def test_no_offer_in_the_afternoon_or_after_a_briefing(make_app: MakeApp) -> None:
    h = make_app([reply("Done.")], overrides={"briefing": {"offer": True}})
    morning(h, hour=15)
    assert "briefing" not in (await h.app.agent.run_turn("open notepad")).text
    h2 = make_app(overrides={"briefing": {"offer": True}})
    morning(h2)
    await h2.app.agent.run_turn("good morning")
    assert h2.app.services.prefs is not None
    assert h2.app.services.prefs.get("briefing.offered_on") == "2026-10-21"


def test_calendar_url_is_the_fake_one() -> None:
    assert CALENDAR_URL.startswith("https://calendar.test/")
