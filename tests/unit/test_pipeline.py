"""The router pipeline (ADR-083): each stage, the order, and the time limit."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from jarvis.core import pipeline
from jarvis.core.pipeline import RouteRequest, route
from tests.conftest import Harness, MakeApp

STAGES = ["exact_phrase", "arithmetic", "template", "agent"]


async def routed(h: Harness, text: str, stages: list[str] = STAGES) -> Any:
    found, _ = await route(RouteRequest(text, h.app.registry, h.app.services), stages, 1000)
    return None if found is None else (found.stage, found.name, json.loads(found.arguments))


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("pause the music", ("exact_phrase", "media_control", {"action": "pause"})),
        ("what's 12 times 7", ("arithmetic", "calculate", {"expression": "12 * 7"})),
        ("open notepad", ("template", "open_app", {"name": "Notepad"})),
        ("Jarvis, open the calculator app", ("template", "open_app", {"name": "Calculator"})),
        ("set the volume to 30", ("template", "set_volume", {"level": 30})),
        ("volume 30 percent", ("template", "set_volume", {"level": 30})),
        ("mute", ("template", "set_volume", {"mute": True})),
        ("note that the bin goes out", ("template", "take_note", {"text": "the bin goes out"})),
        ("jot down buy milk", ("template", "take_note", {"text": "buy milk"})),
        ("make a note: call the bank", ("template", "take_note", {"text": "call the bank"})),
    ],
)
async def test_stages_handle_their_commands(make_app: MakeApp, said: str, expected: Any) -> None:
    assert await routed(make_app(), said) == expected


@pytest.mark.parametrize(
    "said",
    [
        "open my report",
        "open youtube",
        "volume 300",
        "message mom that I'm late",
        "hi",
        "add a note to call mom",
        "add a note to the meeting invite",
    ],
)
async def test_everything_else_goes_to_the_model(make_app: MakeApp, said: str) -> None:
    assert await routed(make_app(), said) is None


async def test_a_stage_left_out_of_the_pipeline_does_not_run(make_app: MakeApp) -> None:
    assert await routed(make_app(), "open notepad", ["exact_phrase", "agent"]) is None


async def test_a_slow_stage_is_skipped(make_app: MakeApp, monkeypatch: pytest.MonkeyPatch) -> None:
    async def slow(request: RouteRequest) -> tuple[str, str]:
        await asyncio.sleep(5)
        return "calculate", "{}"

    monkeypatch.setitem(pipeline.STAGES, "template", slow)
    h = make_app()
    found, times = await route(
        RouteRequest("open notepad", h.app.registry, h.app.services), STAGES, 50
    )
    assert found is None
    assert times["template"] < 1000


async def test_a_match_for_a_missing_tool_is_ignored(make_app: MakeApp) -> None:
    from jarvis.tools.registry import Registry

    h = make_app()
    request = RouteRequest("what's 12 times 7", Registry(), h.app.services)  # no tools at all
    found, _ = await route(request, STAGES, 1000)
    assert found is None
