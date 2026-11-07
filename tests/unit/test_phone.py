"""Phase 29: reaching your own phone for free, through KDE Connect and ntfy (ADR-098).

Nothing here touches a real phone: KDE Connect is a fake runner and ntfy a mock transport.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from jarvis.adapters.phone import Phone, PhoneError, parse_devices
from jarvis.bridge.phone import NtfyAsker, PhoneAlertAsker, phone_asker
from jarvis.bridge.service import BridgeRequest
from jarvis.config import PhoneSettings
from jarvis.core.events import EventBus
from jarvis.core.fast_path import exact_call
from jarvis.core.tool_routing import select_tools
from jarvis.llm.types import ToolCall
from jarvis.platform import display
from jarvis.storage.db import Database
from jarvis.tools.base import ContextFlags, Risk, ToolContext
from jarvis.tools.catalog import build_registry
from jarvis.tools.policy import PolicyGate
from jarvis.tools.system.reminders import Reminders, ReminderScheduler
from tests.conftest import FakeChannel, Harness, MakeApp

PAIRED = "- OnePlus Nord2 5G: 0a1b2c3d4e5f on 192.168.68.110 via LAN (paired and reachable)"
UNPAIRED = "- OnePlus Nord2 5G: 0a1b2c3d4e5f on 192.168.68.110 via LAN (reachable)"
AWAY = "- OnePlus Nord2 5G: 0a1b2c3d4e5f (paired)"


class FakeKde:
    """kdeconnect-cli: records every command and answers --list-devices with `listing`."""

    def __init__(self, listing: str = PAIRED, fail: str | None = None) -> None:
        self.listing = listing
        self.fail = fail  # an action that fails, such as "--ping-msg"
        self.calls: list[list[str]] = []

    async def __call__(self, args: list[str], timeout_s: float) -> str:
        self.calls.append(args)
        if args == ["--list-devices"]:
            return f"{self.listing}\n1 device found\n"
        if self.fail and self.fail in args:
            raise PhoneError("KDE Connect failed: the phone went away")
        return ""

    def actions(self) -> list[list[str]]:
        return [call for call in self.calls if call != ["--list-devices"]]


class Ntfy:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.sent.append(json.loads(request.content))
        return httpx.Response(200, json={"id": "x"})

    def client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle))


def make_phone(kde: FakeKde, ntfy: Ntfy | None = None, **settings: Any) -> Phone:
    cfg = PhoneSettings(**settings)
    return Phone(cfg, runner=kde, http=(ntfy or Ntfy()).client(), ntfy_token="")


@pytest.fixture
def setup(make_app: MakeApp) -> Callable[..., tuple[Harness, FakeKde, Ntfy]]:
    def build(
        listing: str = PAIRED, *, topic: str = "", channel: FakeChannel | None = None, **kw: Any
    ) -> tuple[Harness, FakeKde, Ntfy]:
        h = make_app(channel=channel)
        kde, ntfy = FakeKde(listing, **kw), Ntfy()
        h.app.services.phone = make_phone(kde, ntfy, ntfy_topic=topic)
        return h, kde, ntfy

    return build


def context(h: Harness, flags: ContextFlags | None = None) -> ToolContext:
    return ToolContext(h.app.settings, h.channel, h.app.services, "s", "t", flags or ContextFlags())


async def call(h: Harness, tool: str, flags: ContextFlags | None = None, **args: Any) -> Any:
    return await h.app.agent.executor.run(ToolCall("c1", tool, json.dumps(args)), context(h, flags))


# The device list


def test_devices_are_read_from_the_full_list() -> None:
    (paired,) = parse_devices(PAIRED)
    assert (paired.name, paired.id, paired.usable) == ("OnePlus Nord2 5G", "0a1b2c3d4e5f", True)
    (unpaired,) = parse_devices(UNPAIRED)  # what this laptop showed before pairing
    assert unpaired.reachable
    assert not unpaired.paired
    (away,) = parse_devices(AWAY)
    assert away.paired
    assert not away.reachable
    assert parse_devices("0 devices found") == []


async def test_an_unpaired_phone_says_how_to_pair_it() -> None:
    phone = make_phone(FakeKde(UNPAIRED))
    assert await phone.device() is None
    why = await phone.why_not()
    assert "not paired" in why
    assert "Pair" in why
    assert "ntfy_topic" in why


async def test_several_phones_need_a_name_and_the_name_picks_one() -> None:
    two = PAIRED + "\n- Pixel 8: 99aa88bb77cc on 192.168.68.111 via LAN (paired and reachable)"
    assert await make_phone(FakeKde(two)).device() is None
    assert "Several phones" in await make_phone(FakeKde(two)).why_not()
    chosen = await make_phone(FakeKde(two), device="pixel 8").device()
    assert chosen is not None
    assert chosen.name == "Pixel 8"


async def test_kde_connect_missing_is_explained() -> None:
    phone = Phone(PhoneSettings(kdeconnect_cli="no-such-kdeconnect-cli-here"), ntfy_token="")
    assert await phone.device() is None
    assert "not installed" in await phone.why_not()


# ring_phone


async def test_ring_rings_the_paired_phone_without_asking(setup: Any) -> None:
    h, kde, _ = setup()
    outcome = await call(h, "ring_phone")
    assert outcome.result.ok, outcome.result.error
    assert kde.actions() == [["--device", "0a1b2c3d4e5f", "--ring"]]
    assert "OnePlus" in outcome.result.speech
    assert h.channel.requests == []


async def test_ring_falls_back_to_an_urgent_push_when_the_phone_is_away(setup: Any) -> None:
    h, kde, ntfy = setup(AWAY, topic="jarvis-test-topic")
    outcome = await call(h, "ring_phone")
    assert outcome.result.ok
    assert kde.actions() == []
    assert ntfy.sent[0]["topic"] == "jarvis-test-topic"
    assert ntfy.sent[0]["priority"] == 5


async def test_ring_with_no_way_explains_what_to_set_up(setup: Any) -> None:
    h, _, ntfy = setup(UNPAIRED)
    outcome = await call(h, "ring_phone")
    assert not outcome.result.ok
    assert "not paired" in outcome.result.error
    assert ntfy.sent == []


def test_find_my_phone_is_an_exact_phrase_and_phone_words_offer_the_tools() -> None:
    assert exact_call("find my phone") == ("ring_phone", "{}")
    assert exact_call("Jarvis, where's my phone?") == ("ring_phone", "{}")
    names = {tool.name for tool in select_tools("send this file to my phone", build_registry())}
    assert {"send_to_phone", "notify_phone", "ring_phone"} <= names


# notify_phone


async def test_notify_goes_over_kde_connect_without_asking(setup: Any) -> None:
    h, kde, ntfy = setup(topic="t")
    outcome = await call(h, "notify_phone", message="The build finished.", title="CI")
    assert outcome.result.ok
    assert kde.actions() == [["--device", "0a1b2c3d4e5f", "--ping-msg", "CI: The build finished."]]
    assert ntfy.sent == []
    assert h.channel.requests == []


async def test_private_data_over_ntfy_asks_first(setup: Any) -> None:
    h, _, ntfy = setup(AWAY, topic="t", channel=FakeChannel(confirm=False))
    outcome = await call(h, "notify_phone", ContextFlags(private=True), message="Your balance")
    assert outcome.decision == "denied"
    assert "internet" in h.channel.requests[0].reason
    assert ntfy.sent == []
    # Without private data in the conversation, the same push needs no question.
    h.channel.requests.clear()
    outcome = await call(h, "notify_phone", message="Claude finished.")
    assert outcome.result.ok
    assert h.channel.requests == []
    assert ntfy.sent[0]["message"] == "Claude finished."


async def test_the_way_is_pinned_when_prepared(setup: Any) -> None:
    # Decided KDE Connect; the phone drops off before it runs: an error, never a silent push.
    h, _, ntfy = setup(topic="t", fail="--ping-msg")
    outcome = await call(h, "notify_phone", message="hello")
    assert not outcome.result.ok
    assert "went away" in outcome.result.error
    assert ntfy.sent == []


async def test_the_gate_sees_the_ntfy_route_as_a_confirm(setup: Any) -> None:
    h, _, _ = setup(AWAY, topic="t")
    tool = build_registry().get("notify_phone")
    assert tool is not None
    ctx = context(h, ContextFlags(private=True))
    prepared = await tool.prepare(ctx, {"message": "x", "title": "", "via": ""})
    assert prepared.args["via"] == "ntfy"
    verdict = PolicyGate(h.app.settings.safety).evaluate(tool, prepared, ctx.flags)
    assert verdict.risk is Risk.CONFIRM


# send_to_phone


async def test_a_file_is_sent_after_a_yes_with_its_exact_path(setup: Any) -> None:
    h, kde, _ = setup()
    report = h.files_root / "Budget 2026.xlsx"
    report.write_bytes(b"x" * 2048)
    outcome = await call(h, "send_to_phone", item=str(report))
    assert outcome.result.ok, outcome.result.error
    (request,) = h.channel.requests
    assert "Budget 2026.xlsx" in request.summary
    assert "OnePlus" in request.summary
    assert kde.actions() == [["--device", "0a1b2c3d4e5f", "--share", str(report.resolve())]]


async def test_a_no_sends_nothing(setup: Any) -> None:
    h, kde, _ = setup(channel=FakeChannel(confirm=False))
    outcome = await call(h, "send_to_phone", item="clipboard")
    assert outcome.decision == "denied"
    assert kde.actions() == []


async def test_secret_and_outside_files_are_never_sent(setup: Any, tmp_path: Any) -> None:
    h, kde, _ = setup()
    secret = h.files_root / ".env"
    secret.write_text("KEY=1", "utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("x", "utf-8")
    for path in (secret, outside):
        outcome = await call(h, "send_to_phone", item=str(path))
        assert not outcome.result.ok
    assert kde.actions() == []
    assert h.channel.requests == []


async def test_clipboard_link_and_text(setup: Any) -> None:
    h, kde, _ = setup()
    assert (await call(h, "send_to_phone", item="the clipboard")).result.ok
    assert (await call(h, "send_to_phone", item="https://example.com/a")).result.ok
    assert (await call(h, "send_to_phone", text="12 MG Road")).result.ok
    assert [call[2:] for call in kde.actions()] == [
        ["--send-clipboard"],
        ["--share", "https://example.com/a"],
        ["--share-text", "12 MG Road"],
    ]
    assert len(h.channel.requests) == 3  # each one asked


async def test_a_screenshot_is_taken_only_after_the_yes(setup: Any, monkeypatch: Any) -> None:
    taken: list[str] = []

    def capture(path: Any) -> tuple[int, int]:
        taken.append(str(path))
        return 1, 1

    monkeypatch.setattr(display, "capture_screen", capture)
    h, kde, _ = setup(channel=FakeChannel(confirm=False))
    await call(h, "send_to_phone", item="screenshot")
    assert taken == []
    h.channel._confirm = True
    outcome = await call(h, "send_to_phone", item="a screenshot")
    assert outcome.result.ok
    assert kde.actions()[0][2:] == ["--share", taken[0]]


async def test_an_unreachable_phone_fails_before_asking(setup: Any) -> None:
    h, _, _ = setup(AWAY)
    outcome = await call(h, "send_to_phone", item="clipboard")
    assert not outcome.result.ok
    assert h.channel.requests == []


# Reminders that ring the phone


async def test_a_phone_reminder_rings_and_a_plain_one_does_not(setup: Any) -> None:
    h, _, _ = setup()
    await call(h, "set_reminder", message="call the bank", in_minutes=5, on_phone=True)
    await call(h, "set_reminder", message="stretch", in_minutes=5)
    listed = await call(h, "list_reminders")
    assert [item.get("on_phone", False) for item in listed.result.data] == [True, False]

    db = Database(":memory:")
    now = [1000.0]
    reminders = Reminders(db, clock=lambda: now[0])
    reminders.add("reminder", "call the bank", 1000.0, {"phone": True})
    reminders.add("reminder", "stretch", 1000.0)
    alerts: list[str] = []
    said: list[str] = []

    async def alert(text: str) -> str:
        alerts.append(text)
        return "kdeconnect"

    async def announce(text: str) -> None:
        said.append(text)

    scheduler = ReminderScheduler(reminders, EventBus(), announce, alert_phone=alert)
    for item in reminders.pending():
        await scheduler._fire(item, now[0])
    assert alerts == ["Reminder: call the bank."]
    assert said == ["Reminder: call the bank.", "Reminder: stretch."]


async def test_a_phone_that_cannot_be_reached_still_lets_the_reminder_speak() -> None:
    reminders = Reminders(Database(":memory:"), clock=lambda: 1000.0)
    reminders.add("reminder", "tea", 1000.0, {"phone": True})
    said: list[str] = []

    async def alert(text: str) -> str:
        raise PhoneError("no phone")

    async def announce(text: str) -> None:
        said.append(text)

    scheduler = ReminderScheduler(reminders, EventBus(), announce, alert_phone=alert)
    (item,) = reminders.pending()
    await scheduler._fire(item, 1000.0)
    assert said == ["Reminder: tea."]


async def test_alert_rings_after_the_notification_and_falls_back_to_ntfy() -> None:
    kde, ntfy = FakeKde(), Ntfy()
    phone = make_phone(kde, ntfy, ntfy_topic="t")
    assert await phone.alert("call the bank", ring=True) == "kdeconnect"
    assert [call[2] for call in kde.actions()] == ["--ping-msg", "--ring"]
    away = make_phone(FakeKde(AWAY), ntfy, ntfy_topic="t")
    assert await away.alert("call the bank", ring=True) == "ntfy"
    assert ntfy.sent[-1]["priority"] == 5


# The Claude Code bridge


async def test_claude_waiting_pings_the_phone_and_the_pc_keeps_waiting() -> None:
    kde = FakeKde()
    asker = PhoneAlertAsker(make_phone(kde), None)
    request = BridgeRequest(kind="question", text="Which framework?", options=["React", "Vue"])
    assert await asker(request) is None
    ((_, _, flag, text),) = kde.actions()
    assert flag == "--ping-msg"
    assert "Which framework?" in text
    assert "Answer at the PC" in text


async def test_with_a_topic_the_ntfy_buttons_follow(settings: Any) -> None:
    cfg = settings.model_copy(deep=True)
    cfg.phone.ntfy_topic = "jarvis-test-topic"
    device = make_phone(FakeKde())
    asker = phone_asker(cfg, device=device)
    assert isinstance(asker, PhoneAlertAsker)
    assert isinstance(asker._then, NtfyAsker)
    cfg.phone.ntfy_topic = ""
    assert phone_asker(cfg) is None  # no running Jarvis's phone and no topic: nothing
