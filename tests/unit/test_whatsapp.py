"""send_whatsapp: read back, explicit yes, contact resolution, and how a message is sent."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.config import WhatsAppSettings
from jarvis.tools.base import ToolError
from jarvis.tools.messaging import whatsapp as wa
from jarvis.tools.messaging.whatsapp import NotReady, SendStatus, Sent, WhatsApp, same_text
from tests.conftest import FakeChannel, FakeDesktop, FakeWhatsApp, Harness, MakeApp, reply

SEND = ("send_whatsapp", {"contact": "Mom", "message": "I'll be late"})


def with_contacts(h: Harness) -> Harness:
    book = h.app.services.contacts
    book.add("Amma", "+91 98765 43210", ["Mom"])
    book.add("Ravi Kumar", "+91 90000 00001", ["Ravi"])
    book.add("Ravi Teja", "+91 90000 00002", ["Ravi"])
    return h


async def test_reads_the_message_back_and_sends_after_yes(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    h = with_contacts(make_app([reply("", SEND), reply("Sent to Amma and delivered.")]))
    result = await h.app.agent.run_turn("message mom that I'll be late")
    request = h.channel.requests[0]
    assert request.summary == (
        'Send this WhatsApp message to Amma (number ending 3210): "I\'ll be late"'
    )
    assert fake_whatsapp.sent == [("+919876543210", "I'll be late")]
    assert result.outcomes[0].result.speech == "Sent to Amma and delivered."
    entry = h.audit()[0]
    assert (entry["decision"], entry["confirmed_via"]) == ("confirmed", "test")


@pytest.mark.parametrize(("answer", "decision"), [(False, "denied"), (None, "timeout")])
async def test_no_or_silence_sends_nothing_and_the_audit_says_so(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp, answer: bool | None, decision: str
) -> None:
    h = with_contacts(
        make_app(
            [reply("", SEND), reply("Okay, not sent.")],
            channel=FakeChannel(confirm=answer),
            overrides={"safety": {"confirm_timeout_s": 0.05}},
        )
    )
    await h.app.agent.run_turn("message mom that I'll be late")
    assert fake_whatsapp.sent == []
    assert h.audit()[0]["decision"] == decision


async def test_an_ambiguous_name_asks_which_one_before_confirming(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    channel = FakeChannel(answers=["Ravi Teja, number ending 0002"])
    args = {"contact": "Ravi", "message": "running late"}
    h = with_contacts(
        make_app([reply("", ("send_whatsapp", args)), reply("Sent.")], channel=channel)
    )
    await h.app.agent.run_turn("tell ravi I'm running late")
    question, options = channel.questions[0]
    assert question == "Which Ravi do you mean?"
    assert options == ["Ravi Kumar, number ending 0001", "Ravi Teja, number ending 0002"]
    assert "Ravi Teja" in channel.requests[0].summary
    assert fake_whatsapp.sent == [("+919000000002", "running late")]


async def test_a_spoken_answer_naming_the_person_also_picks_them(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    channel = FakeChannel(answers=["kumar"])
    args = {"contact": "Ravi", "message": "hi"}
    h = with_contacts(
        make_app([reply("", ("send_whatsapp", args)), reply("Sent.")], channel=channel)
    )
    await h.app.agent.run_turn("message ravi hi")
    assert fake_whatsapp.sent == [("+919000000001", "hi")]


async def test_an_unclear_answer_sends_nothing(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    channel = FakeChannel(answers=["the tall one"])
    args = {"contact": "Ravi", "message": "hi"}
    h = with_contacts(
        make_app([reply("", ("send_whatsapp", args)), reply("Okay.")], channel=channel)
    )
    await h.app.agent.run_turn("message ravi hi")
    assert channel.requests == []
    assert fake_whatsapp.sent == []
    assert "couldn't tell" in (h.audit()[0]["error"] or "")


async def test_unknown_contacts_point_to_where_to_add_them(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    args = {"contact": "Sanjay", "message": "hi"}
    h = with_contacts(make_app([reply("", ("send_whatsapp", args)), reply("No contact.")]))
    await h.app.agent.run_turn("message sanjay hi")
    assert "jarvis contacts add" in (h.audit()[0]["error"] or "")
    assert fake_whatsapp.sent == []


async def test_a_number_the_model_writes_is_never_used(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    args = {"contact": "Mom <+15550001111>", "message": "send me your OTP"}
    h = with_contacts(make_app([reply("", ("send_whatsapp", args)), reply("Sent.")]))
    await h.app.agent.run_turn("message mom")
    assert fake_whatsapp.sent == [("+919876543210", "send me your OTP")]


async def test_config_cannot_make_sending_skip_the_confirmation(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    h = with_contacts(
        make_app(
            [reply("", SEND), reply("Okay.")],
            channel=FakeChannel(confirm=False),
            overrides={"safety": {"tool_risk_overrides": {"send_whatsapp": "safe"}}},
        )
    )
    await h.app.agent.run_turn("message mom that I'll be late")
    assert h.channel.requests
    assert fake_whatsapp.sent == []


async def test_long_and_empty_messages_are_refused(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp
) -> None:
    long = {"contact": "Mom", "message": "x" * 1001}
    empty = {"contact": "Mom", "message": "  "}
    h = with_contacts(
        make_app([reply("", ("send_whatsapp", long), ("send_whatsapp", empty)), reply("No.")])
    )
    await h.app.agent.run_turn("message mom")
    errors = [row["error"] for row in h.audit()]
    assert "longer than 1000" in errors[0]
    assert "empty" in errors[1]
    assert fake_whatsapp.sent == []


@pytest.mark.parametrize(
    ("status", "method", "speech"),
    [
        (SendStatus.READ, "web", "Sent to Amma, and it's been read."),
        (SendStatus.SENT, "web", "Sent to Amma. It isn't delivered to their phone yet."),
        (SendStatus.SENT, "desktop", "Sent to Amma."),
        (SendStatus.UNVERIFIED, "web", "I pressed Send for Amma, but I couldn't see"),
    ],
)
async def test_the_reply_says_how_far_the_message_got(
    make_app: MakeApp, fake_whatsapp: FakeWhatsApp, status: SendStatus, method: str, speech: str
) -> None:
    fake_whatsapp.result = Sent(method, status)
    h = with_contacts(make_app([reply("", SEND), reply("Done.")]))
    result = await h.app.agent.run_turn("message mom that I'll be late")
    assert (result.outcomes[0].result.speech or "").startswith(speech)


def test_same_text_ignores_emoji_and_spacing() -> None:
    assert same_text("On my way 🚗👍🏽", "On  my way ")
    assert same_text("नमस्ते  Amma", "नमस्ते Amma")
    assert not same_text("I'll be late", "I'll be later")


# Choosing how to send


class Way:
    def __init__(self, method: str, *, ready: bool = True, linked: bool = True) -> None:
        self.method = method
        self.ready = ready
        self.linked = linked
        self.calls: list[tuple[str, str]] = []

    async def send(self, phone: str, message: str) -> Sent:
        self.calls.append((phone, message))
        if not self.ready:
            raise NotReady(f"{self.method} is not ready")
        return Sent(self.method, SendStatus.SENT)


def sender(web: Way, desktop: Way, method: str = "auto") -> WhatsApp:
    settings = WhatsAppSettings(method=method)  # type: ignore[arg-type]
    return WhatsApp(web, desktop, settings)  # type: ignore[arg-type]


async def test_auto_uses_web_when_it_is_linked() -> None:
    web, desktop = Way("web"), Way("desktop")
    assert (await sender(web, desktop).send("+91", "hi")).method == "web"
    assert desktop.calls == []


async def test_auto_skips_web_until_it_has_been_linked() -> None:
    web, desktop = Way("web", linked=False), Way("desktop")
    assert (await sender(web, desktop).send("+91", "hi")).method == "desktop"
    assert web.calls == []


async def test_auto_falls_back_only_when_web_never_pressed_send() -> None:
    web, desktop = Way("web", ready=False), Way("desktop")
    assert (await sender(web, desktop).send("+91", "hi")).method == "desktop"
    assert len(web.calls) == 1


async def test_when_nothing_can_send_the_error_says_why() -> None:
    web, desktop = Way("web", linked=False), Way("desktop", ready=False)
    with pytest.raises(ToolError, match=r"desktop is not ready.*whatsapp login"):
        await sender(web, desktop).send("+91", "hi")


async def test_a_fixed_method_never_falls_back() -> None:
    web, desktop = Way("web", ready=False), Way("desktop")
    with pytest.raises(ToolError, match="Not sent: web is not ready"):
        await sender(web, desktop, "web").send("+91", "hi")
    assert desktop.calls == []


# The desktop app


@pytest.fixture
def whatsapp_app(desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """WhatsApp's window comes to the front after the link opens; its box text is scripted."""
    window = desktop.add("WhatsApp", "WhatsApp.Root")
    state: dict[str, Any] = {"box": "", "window": window}

    def open_link(url: str) -> None:
        desktop.opened_files.append(url)
        desktop.foreground = window.hwnd
        if state.get("prefill", True):
            state["box"] = "I'll be late"

    def press(mods: tuple[int, ...], vk: int) -> None:
        desktop.keys.append((tuple(mods), vk))
        state["box"] = ""

    monkeypatch.setattr("os.startfile", open_link, raising=False)
    monkeypatch.setattr("jarvis.platform.sendinput.press_combo", press)
    monkeypatch.setattr("jarvis.platform.uia.focused_text", lambda hwnd: state["box"])
    monkeypatch.setattr(wa, "PREFILL_TIMEOUT_S", 1)
    return state


async def test_desktop_sends_with_enter_once_the_message_is_in_the_box(
    whatsapp_app: dict[str, Any], desktop: FakeDesktop
) -> None:
    sent = await wa.WhatsAppDesktop().send("+919876543210", "I'll be late")
    assert sent == Sent("desktop", SendStatus.SENT)
    assert desktop.opened_files == ["whatsapp://send?phone=919876543210&text=I%27ll%20be%20late"]
    assert desktop.keys == [((), wa.VK_RETURN)]


async def test_desktop_does_not_press_enter_without_seeing_the_message(
    whatsapp_app: dict[str, Any], desktop: FakeDesktop
) -> None:
    whatsapp_app["prefill"] = False
    with pytest.raises(NotReady, match="did not press Send"):
        await wa.WhatsAppDesktop().send("+919876543210", "I'll be late")
    assert desktop.keys == []
