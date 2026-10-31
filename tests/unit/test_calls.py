"""call_contact and hang_up: a confirmed contact is called. No real call is ever placed."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.platform import uia
from jarvis.tools.messaging import whatsapp as wa
from jarvis.tools.messaging.whatsapp import NotReady
from tests.conftest import FakeChannel, FakeDesktop, MakeApp, reply

MOM = "+919876543210"
PHONE_LINK = {"calls": {"method": "phone_link"}}


@pytest.fixture
def dialed(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    numbers: list[str] = []
    monkeypatch.setattr("jarvis.tools.messaging.calls.dial", numbers.append)
    return numbers


@pytest.fixture
def called(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    numbers: list[str] = []

    async def fake_call(phone: str) -> bool:
        numbers.append(phone)
        return True

    monkeypatch.setattr("jarvis.tools.messaging.calls.whatsapp_call", fake_call)
    return numbers


async def test_a_call_needs_a_yes_and_uses_whatsapp(
    make_app: MakeApp, called: list[str], dialed: list[str]
) -> None:
    h = make_app([reply("", ("call_contact", {"contact": "mom"})), reply("Calling.")])
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    result = await h.app.agent.run_turn("call mom")
    assert called == [MOM]
    assert dialed == []
    assert h.channel.requests[0].summary == "WhatsApp call Amma (number ending 3210)"
    assert result.outcomes[0].decision.value == "confirmed"
    assert result.outcomes[0].result.speech == "Calling Amma on WhatsApp."


async def test_phone_link_is_used_when_chosen(
    make_app: MakeApp, called: list[str], dialed: list[str]
) -> None:
    h = make_app(
        [reply("", ("call_contact", {"contact": "mom"})), reply("Calling.")],
        overrides=PHONE_LINK,
    )
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    await h.app.agent.run_turn("call mom")
    assert dialed == [MOM]
    assert called == []
    assert h.channel.requests[0].summary == "Call Amma (number ending 3210) from your phone"


async def test_no_means_no_call(make_app: MakeApp, called: list[str], dialed: list[str]) -> None:
    h = make_app(
        [reply("", ("call_contact", {"contact": "mom"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
    )
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    await h.app.agent.run_turn("call mom")
    assert called == []
    assert dialed == []


async def test_an_unknown_contact_is_not_called(make_app: MakeApp, called: list[str]) -> None:
    h = make_app([reply("", ("call_contact", {"contact": "zork"})), reply("No such contact.")])
    await h.app.agent.run_turn("call zork")
    assert called == []
    assert h.channel.requests == []


async def test_a_number_from_the_model_is_never_called(
    make_app: MakeApp, called: list[str]
) -> None:
    # The model cannot smuggle a number in: the preparer looks the name up again.
    h = make_app([reply("", ("call_contact", {"contact": "Amma <+15550000000>"})), reply("ok")])
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    await h.app.agent.run_turn("call amma")
    assert called == [MOM]


async def test_whatsapp_failure_does_not_fall_back_to_phone_link(
    make_app: MakeApp, dialed: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def not_ready(_phone: str) -> bool:
        raise NotReady("WhatsApp did not open that chat")

    monkeypatch.setattr("jarvis.tools.messaging.calls.whatsapp_call", not_ready)
    h = make_app([reply("", ("call_contact", {"contact": "mom"})), reply("No call.")])
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    result = await h.app.agent.run_turn("call mom")
    assert dialed == []
    assert "No call was made" in (result.outcomes[0].result.error or "")


async def test_an_unseen_call_is_reported_honestly(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def unseen(_phone: str) -> bool:
        return False

    monkeypatch.setattr("jarvis.tools.messaging.calls.whatsapp_call", unseen)
    h = make_app([reply("", ("call_contact", {"contact": "mom"})), reply("Check it.")])
    h.app.services.contacts.add("Amma", MOM, aliases=["mom"])
    result = await h.app.agent.run_turn("call mom")
    assert "couldn't see the call start" in (result.outcomes[0].result.speech or "")


def test_routing_offers_calls() -> None:
    from jarvis.core.tool_routing import select_tools
    from jarvis.tools.catalog import build_registry

    registry = build_registry()
    assert "call_contact" in {t.name for t in select_tools("call my mom", registry)}
    assert "hang_up" in {t.name for t in select_tools("hang up", registry)}


# The WhatsApp app itself


@pytest.fixture
def app_window(desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """WhatsApp's window, its scripted message box, and a record of every button pressed."""
    window = desktop.add("WhatsApp", "WhatsApp.Root")
    state: dict[str, Any] = {
        "box": "",
        "prefill": True,
        "clears": True,
        "pressed": [],
        "buttons": {"Voice call"},
        "after_press": {"End call"},
    }

    def open_link(url: str) -> None:
        desktop.opened_files.append(url)
        desktop.foreground = window.hwnd
        if state["prefill"]:
            state["box"] = url.rsplit("text=", 1)[1]

    def keys(mods: tuple[int, ...], vk: int) -> None:
        desktop.keys.append((tuple(mods), vk))
        if vk == wa.VK_BACKSPACE and state["clears"]:
            state["box"] = ""

    def press(_hwnd: int, control: uia.Control) -> str:
        if control.kind != "button" or control.name not in state["buttons"]:
            raise uia.UIAError("not there")
        state["pressed"].append(control.name)
        if control.name == "Voice call":
            state["buttons"] = state["buttons"] | state["after_press"]
        return "pressed"

    def read(_hwnd: int, _max: int) -> tuple[uia.WindowContent, bool]:
        controls = [uia.Control("button", name) for name in state["buttons"]]
        return uia.WindowContent(lines=[], controls=controls), False

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr("os.startfile", open_link, raising=False)
    monkeypatch.setattr("jarvis.platform.sendinput.press_combo", keys)
    monkeypatch.setattr("jarvis.platform.uia.focused_text", lambda _hwnd: state["box"])
    monkeypatch.setattr("jarvis.platform.uia.press", press)
    monkeypatch.setattr("jarvis.platform.uia.read_window", read)
    monkeypatch.setattr(wa, "PREFILL_TIMEOUT_S", 1)
    monkeypatch.setattr(wa, "CALL_START_CHECKS", 1)
    return state


async def test_the_app_clears_the_marker_then_presses_voice_call(
    app_window: dict[str, Any], desktop: FakeDesktop
) -> None:
    assert await wa.WhatsAppDesktop().call(MOM) is True
    assert desktop.opened_files[0].startswith("whatsapp://send?phone=919876543210&text=jarvis-")
    assert desktop.keys == [((wa.VK_CONTROL,), wa.VK_A), ((), wa.VK_BACKSPACE)]
    assert app_window["pressed"] == ["Voice call"]
    assert app_window["box"] == ""


async def test_each_call_gets_its_own_marker(
    app_window: dict[str, Any], desktop: FakeDesktop
) -> None:
    await wa.WhatsAppDesktop().call(MOM)
    await wa.WhatsAppDesktop().call(MOM)
    assert desktop.opened_files[0] != desktop.opened_files[1]


async def test_enter_is_never_pressed_for_a_call(
    app_window: dict[str, Any], desktop: FakeDesktop
) -> None:
    await wa.WhatsAppDesktop().call(MOM)
    assert all(vk != wa.VK_RETURN for _mods, vk in desktop.keys)


async def test_a_chat_that_did_not_open_is_never_called(
    app_window: dict[str, Any], desktop: FakeDesktop
) -> None:
    # The previous chat stays open when a link fails: its button would ring the wrong person.
    app_window["prefill"] = False
    app_window["box"] = "someone else's draft"
    with pytest.raises(NotReady, match="did not open that chat"):
        await wa.WhatsAppDesktop().call(MOM)
    assert app_window["pressed"] == []
    assert desktop.keys == []


async def test_a_marker_that_stays_stops_the_call(app_window: dict[str, Any]) -> None:
    app_window["clears"] = False
    with pytest.raises(NotReady, match="could not clear"):
        await wa.WhatsAppDesktop().call(MOM)
    assert app_window["pressed"] == []


async def test_no_voice_call_button_means_no_call(app_window: dict[str, Any]) -> None:
    app_window["buttons"] = set()
    with pytest.raises(NotReady, match="Voice call button"):
        await wa.WhatsAppDesktop().call(MOM)


async def test_a_call_that_does_not_appear_is_not_claimed(app_window: dict[str, Any]) -> None:
    app_window["after_press"] = set()
    assert await wa.WhatsAppDesktop().call(MOM) is False


async def test_hang_up_presses_the_end_call_button(app_window: dict[str, Any]) -> None:
    app_window["buttons"] = {"Voice call", "End call"}
    assert await wa.WhatsAppDesktop().hang_up() is True
    assert app_window["pressed"] == ["End call"]


async def test_hang_up_with_no_call_presses_nothing(app_window: dict[str, Any]) -> None:
    assert await wa.WhatsAppDesktop().hang_up() is False
    assert app_window["pressed"] == []


async def test_hang_up_tool_reports_no_call(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def nothing() -> bool:
        return False

    monkeypatch.setattr("jarvis.tools.messaging.calls.whatsapp_hang_up", nothing)
    h = make_app([reply("", ("hang_up", {})), reply("No call is on.")])
    result = await h.app.agent.run_turn("hang up")
    assert "couldn't find a WhatsApp call" in (result.outcomes[0].result.error or "")
