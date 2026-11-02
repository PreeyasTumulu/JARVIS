"""The model router and the privacy guard: what may go to a cloud model, and what never does."""

from __future__ import annotations

import dataclasses
from typing import Any

import pytest

from jarvis.llm.router import CLOUD_TOOLS, CloudModel, PrivacyViolation, wants_cloud
from jarvis.llm.types import LLMError, LLMReply
from jarvis.tools.base import Sensitivity
from tests.conftest import FakeLLM, FakeNotificationCenter, Harness, MakeApp, reply

HEAVY = "think harder: why did the Roman empire fall in the west but not in the east"
SECRET = "SECRET-ravi-says-the-merger-is-on"


class FakeCloud(FakeLLM):
    """A cloud model that remembers everything it was sent."""

    def __init__(self, script: list[Any], name: str = "openai/gpt-oss-120b") -> None:
        super().__init__(script)
        self.name = name

    @property
    def model(self) -> str:
        return self.name

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMReply:
        answer = await super().complete(messages, tools)
        return dataclasses.replace(answer, model=self.name)

    def everything_sent(self) -> str:
        return str(self.requests) + str(self.tools_seen)


@pytest.mark.parametrize(
    "text",
    [
        HEAVY,
        "explain the difference between TCP and UDP for a beginner please",
        "use the cloud model to compare python and rust for a web backend",
        "should I learn go or rust first if I already know python well",
    ],
)
def test_heavy_public_questions_may_go_to_the_cloud(text: str) -> None:
    assert wants_cloud(text, "auto")


@pytest.mark.parametrize(
    "text",
    [
        "open notepad",
        "what's the weather",
        "think harder about what is in my resume file",
        "think harder about my notifications and who wrote",
        "explain what is on my clipboard right now in detail please",
        "think harder: what should I reply to the message from Ravi",
        "remember that my manager is Ravi and think harder about it",
    ],
)
def test_private_or_simple_requests_stay_local(text: str) -> None:
    assert not wants_cloud(text, "auto")


def test_escalation_modes() -> None:
    explain = "explain the difference between TCP and UDP for a beginner please"
    assert not wants_cloud(explain, "explicit")
    assert wants_cloud(HEAVY, "explicit")
    assert not wants_cloud(HEAVY, "never")


async def test_the_guard_refuses_private_content_and_private_tools() -> None:
    cloud = CloudModel("groq", FakeCloud([]))
    public = [{"type": "function", "function": {"name": "web_search"}}]
    with pytest.raises(PrivacyViolation):
        await cloud.complete([{"role": "user", "content": "hi"}], public, private=True)
    private_tool = [{"type": "function", "function": {"name": "read_file"}}]
    with pytest.raises(PrivacyViolation):
        await cloud.complete([{"role": "user", "content": "hi"}], private_tool, private=False)


def test_cloud_tools_are_all_public_and_read_only() -> None:
    from jarvis.tools.base import Risk
    from jarvis.tools.catalog import build_registry

    registry = build_registry()
    for name in CLOUD_TOOLS:
        item = registry.get(name)
        assert item is not None
        assert item.sensitivity is Sensitivity.PUBLIC
        assert item.risk is Risk.SAFE


async def test_a_heavy_public_question_goes_to_the_cloud(make_app: MakeApp) -> None:
    groq = FakeCloud([reply("The west faced more invasions and a weaker economy.")])
    h = make_app([], cloud={"groq": groq})
    result = await h.app.agent.run_turn(HEAVY)
    assert result.model == "openai/gpt-oss-120b"
    assert result.text.startswith("The west")
    assert h.llm.requests == []  # the local model was not asked
    sent = groq.requests[0]
    assert [m["role"] for m in sent] == ["system", "user"]
    assert {t["function"]["name"] for t in groq.tools_seen[0] or []} == set(CLOUD_TOOLS)
    usage = h.app.db.execute("SELECT provider, requests FROM cloud_usage")
    assert [tuple(row) for row in usage] == [("groq", 1)]


async def test_private_history_and_memories_never_reach_the_cloud(
    make_app: MakeApp, notification_center: FakeNotificationCenter
) -> None:
    notification_center.add("WhatsApp", "Ravi", SECRET)
    groq = FakeCloud([reply("An answer.")])
    h = make_app([reply("", ("read_notifications", {})), reply(SECRET)], cloud={"groq": groq})
    h.app.services.memory.add(f"The user's code word is {SECRET}")
    await h.app.agent.run_turn("read my notifications")
    await h.app.agent.run_turn(HEAVY)
    assert groq.requests, "the heavy question should have gone to the cloud"
    assert SECRET not in groq.everything_sent()
    assert SECRET in str(h.llm.requests)  # the local model did see both


async def test_a_turn_about_private_data_stays_local(make_app: MakeApp) -> None:
    groq = FakeCloud([reply("never")])
    h = make_app([reply("", ("clipboard_read", {})), reply("It says hello.")], cloud={"groq": groq})
    result = await h.app.agent.run_turn(
        "think harder and explain what is on my clipboard right now please"
    )
    assert groq.requests == []
    assert result.sensitivity is Sensitivity.PRIVATE


async def test_the_cloud_can_use_public_tools(make_app: MakeApp) -> None:
    groq = FakeCloud(
        [
            reply("", ("web_search", {"query": "fall of the western roman empire causes"})),
            reply("Mostly invasions, money, and politics."),
        ]
    )
    h = make_app([], cloud={"groq": groq})
    result = await h.app.agent.run_turn(HEAVY)
    assert [o.call.name for o in result.outcomes] == ["web_search"]
    assert result.text == "Mostly invasions, money, and politics."
    assert h.audit()[0]["tool"] == "web_search"


async def test_asking_for_a_local_tool_hands_the_turn_back(make_app: MakeApp) -> None:
    groq = FakeCloud([reply("", ("read_file", {"path": "C:/secret.txt"}))])
    h = make_app([reply("Answered locally.")], cloud={"groq": groq})
    result = await h.app.agent.run_turn(HEAVY)
    assert result.text == "Answered locally."
    assert h.audit() == []  # read_file never ran for the cloud


async def test_a_failing_provider_hands_over_to_the_next(make_app: MakeApp) -> None:
    groq = FakeCloud([LLMError("rate limited (429)")])
    openrouter = FakeCloud([reply("From OpenRouter."), reply("Again.")], name="nemotron")
    h = make_app([], cloud={"groq": groq, "openrouter": openrouter})
    first = await h.app.agent.run_turn(HEAVY)
    assert (first.text, first.model) == ("From OpenRouter.", "nemotron")
    await h.app.agent.run_turn(HEAVY)
    assert len(groq.requests) == 1  # cooling down after the failure


async def test_when_every_cloud_fails_the_local_model_answers(make_app: MakeApp) -> None:
    groq = FakeCloud([LLMError("down")])
    h = make_app([reply("Local answer.")], cloud={"groq": groq})
    result = await h.app.agent.run_turn(HEAVY)
    assert (result.text, result.model) == ("Local answer.", "fake-model")


async def test_the_daily_cap_keeps_inside_the_free_tier(make_app: MakeApp) -> None:
    groq = FakeCloud([reply("one"), reply("two")])
    h = make_app(
        [reply("Local.")],
        cloud={"groq": groq},
        overrides={"router": {"daily_requests": {"groq": 1}}},
    )
    await h.app.agent.run_turn(HEAVY)
    second = await h.app.agent.run_turn(HEAVY)
    assert second.text == "Local."
    assert len(groq.requests) == 1


async def test_the_answer_joins_the_local_history(make_app: MakeApp) -> None:
    groq = FakeCloud([reply("Invasions.")])
    h: Harness = make_app([reply("As I said, invasions.")], cloud={"groq": groq})
    await h.app.agent.run_turn(HEAVY)
    await h.app.agent.run_turn("and in one word")
    local = h.llm.requests[0]
    assert {"role": "assistant", "content": "Invasions."} in local
