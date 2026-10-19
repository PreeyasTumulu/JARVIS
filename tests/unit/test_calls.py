"""call_contact: Phone Link dials a confirmed contact. No real call is ever placed."""

from __future__ import annotations

import pytest

from tests.conftest import FakeChannel, MakeApp, reply

MOM = "+919876543210"


@pytest.fixture
def dialed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    numbers: list[str] = []
    monkeypatch.setattr("jarvis.tools.messaging.calls.dial", numbers.append)
    return numbers


async def test_a_call_needs_a_yes(make_app: MakeApp, dialed: list[str]) -> None:
    h = make_app([reply("", ("call_contact", {"contact": "mom"})), reply("Calling.")])
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    result = await h.app.agent.run_turn("call mom")
    assert dialed == [MOM]
    assert h.channel.requests[0].summary == "Call Amma (number ending 3210) from your phone"
    assert result.outcomes[0].decision.value == "confirmed"


async def test_no_means_no_call(make_app: MakeApp, dialed: list[str]) -> None:
    h = make_app(
        [reply("", ("call_contact", {"contact": "mom"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
    )
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    await h.app.agent.run_turn("call mom")
    assert dialed == []


async def test_an_unknown_contact_is_not_called(make_app: MakeApp, dialed: list[str]) -> None:
    h = make_app([reply("", ("call_contact", {"contact": "zork"})), reply("No such contact.")])
    await h.app.agent.run_turn("call zork")
    assert dialed == []
    assert h.channel.requests == []


async def test_a_number_from_the_model_is_never_dialed(
    make_app: MakeApp, dialed: list[str]
) -> None:
    # The model cannot smuggle a number in: the preparer looks the name up again.
    h = make_app([reply("", ("call_contact", {"contact": "Amma <+15550000000>"})), reply("ok")])
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    await h.app.agent.run_turn("call amma")
    assert dialed == [MOM]


def test_routing_offers_calls() -> None:
    from jarvis.core.tool_routing import select_tools
    from jarvis.tools.catalog import build_registry

    assert "call_contact" in {t.name for t in select_tools("call my mom", build_registry())}
