"""Semantic routing: groups by meaning when no keyword matched. Embeddings are faked."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis.config import AgentSettings
from jarvis.core.semantic_routing import SemanticRouter
from jarvis.core.tool_routing import needs_meaning
from tests.conftest import MakeApp, reply

# Three axes of meaning; a text's vector counts the words it has from each.
AXES = {
    "calendar": ("tomorrow", "booked", "going", "schedule"),
    "weather": ("jacket", "sunny", "hot", "pour"),
    "media": ("song", "tunes", "track"),
}
EXAMPLES = {
    "calendar": ("what do I have going on tomorrow", "am I booked on friday"),
    "weather": ("do I need a jacket", "will it be sunny"),
    "media": ("skip this song", "put on some tunes"),
}


def vector(text: str) -> list[float]:
    words = text.casefold().split()
    return [float(sum(w in words for w in axis)) + 0.01 for axis in AXES.values()]


class FakeEmbeddings:
    def __init__(self) -> None:
        self.calls: list[list[str]] = []
        self.fail = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.fail:
            return httpx.Response(404, json={"error": "model not found"})
        texts = json.loads(request.content)["input"]
        self.calls.append(texts)
        data = [{"embedding": vector(t.split(": ", 1)[1])} for t in texts]
        return httpx.Response(200, json={"data": data})


@pytest.fixture
def fake() -> FakeEmbeddings:
    return FakeEmbeddings()


def router(fake: FakeEmbeddings, tmp_path: Path, **settings: Any) -> SemanticRouter:
    return SemanticRouter(
        AgentSettings(**settings),
        "http://localhost:11434/v1",
        tmp_path,
        http=httpx.AsyncClient(transport=httpx.MockTransport(fake.handle)),
        examples=EXAMPLES,
    )


async def test_a_paraphrase_finds_its_group(fake: FakeEmbeddings, tmp_path: Path) -> None:
    assert await router(fake, tmp_path).groups("anything going on tomorrow") == ["calendar"]
    assert fake.calls[0][0].startswith("search_query: ")


async def test_nothing_close_enough_means_no_help(fake: FakeEmbeddings, tmp_path: Path) -> None:
    assert await router(fake, tmp_path).groups("tell me a joke") == []


async def test_two_close_groups_are_both_offered(fake: FakeEmbeddings, tmp_path: Path) -> None:
    found = await router(fake, tmp_path).groups("tomorrow hot")
    assert set(found) == {"calendar", "weather"}


async def test_examples_are_embedded_once_and_cached(fake: FakeEmbeddings, tmp_path: Path) -> None:
    await router(fake, tmp_path).groups("schedule tomorrow")
    assert (tmp_path / "route-embeddings.json").exists()
    fake.calls.clear()
    await router(fake, tmp_path).groups("schedule tomorrow")  # a new process, same cache
    assert len(fake.calls) == 1  # only the request itself


async def test_a_missing_model_turns_it_off_quietly(fake: FakeEmbeddings, tmp_path: Path) -> None:
    fake.fail = True
    semantic = router(fake, tmp_path)
    assert await semantic.groups("anything going on tomorrow") == []
    assert not semantic.enabled


async def test_it_can_be_turned_off(fake: FakeEmbeddings, tmp_path: Path) -> None:
    assert await router(fake, tmp_path, semantic_routing=False).groups("going tomorrow") == []
    assert fake.calls == []


def test_keywords_come_first(make_app: MakeApp) -> None:
    registry = make_app().app.registry
    assert not needs_meaning("what's the weather tomorrow", registry)
    assert not needs_meaning("open notepad", registry)
    assert needs_meaning("what do I have going on tomorrow", registry)
    assert needs_meaning("who painted the mona lisa", registry)  # only question words


class FixedGroups:
    def __init__(self, groups: list[str]) -> None:
        self.groups_for: list[str] = groups
        self.asked: list[str] = []

    async def groups(self, text: str) -> list[str]:
        self.asked.append(text)
        return self.groups_for


async def test_the_agent_offers_the_groups_found_by_meaning(make_app: MakeApp) -> None:
    h = make_app([reply("Nothing on tomorrow.")])
    semantic = FixedGroups(["calendar"])
    h.app.services.semantic = semantic  # type: ignore[assignment]
    await h.app.agent.run_turn("anything going on tomorrow")
    offered = {tool["function"]["name"] for tool in h.llm.tools_seen[0] or []}
    assert "calendar_events" in offered
    assert "open_app" not in offered  # not every tool any more
    assert semantic.asked == ["anything going on tomorrow"]


async def test_the_agent_does_not_ask_when_keywords_match(make_app: MakeApp) -> None:
    h = make_app([reply("Opening.")])
    semantic = FixedGroups(["calendar"])
    h.app.services.semantic = semantic  # type: ignore[assignment]
    await h.app.agent.run_turn("open notepad")
    assert semantic.asked == []
