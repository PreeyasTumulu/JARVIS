"""The web UI server: security checks, the WebSocket protocol, confirmations, and shared turns."""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from starlette.websockets import WebSocketDisconnect

from jarvis.core.channel import FirstAnswerChannel
from jarvis.core.events import ToolCallStarted
from jarvis.server.app import create_server
from jarvis.server.hub import WebChannel, WebHub, event_message
from jarvis.server.runtime import BUSY, Runtime
from tests.conftest import Hang, Harness, MakeApp, reply

TOKEN = "per-launch-token"
PORT = 8765
ORIGIN = f"http://testserver:{PORT}"
HOSTS = ("testserver", "127.0.0.1", "localhost")


@contextmanager
def served(make_app: MakeApp, script: Any = ()) -> Iterator[tuple[TestClient, Harness]]:
    hub = WebHub()
    h = make_app(script, channel=FirstAnswerChannel(WebChannel(hub)))
    runtime = Runtime(h.app, hub)
    with TestClient(create_server(runtime, token=TOKEN, port=PORT, hosts=HOSTS)) as client:
        yield client, h


def tab(client: TestClient, token: str = TOKEN, origin: str = ORIGIN) -> Any:
    return client.websocket_connect(f"/ws?token={token}", headers={"origin": origin})


def until(ws: WebSocketTestSession, kind: str, limit: int = 40) -> list[dict[str, Any]]:
    """Messages up to and including the first of `kind`."""
    seen: list[dict[str, Any]] = []
    for _ in range(limit):
        message: dict[str, Any] = ws.receive_json()
        seen.append(message)
        if message["type"] == kind:
            return seen
    raise AssertionError(f"no {kind} in {[m['type'] for m in seen]}")


def test_page_is_served_with_security_headers(make_app: MakeApp) -> None:
    with served(make_app) as (client, _):
        page = client.get("/")
        assert page.status_code == 200
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        assert page.headers["x-frame-options"] == "DENY"
        assert page.headers["referrer-policy"] == "no-referrer"
        assert client.get("/static/app.js").status_code == 200
        assert client.get("/docs").status_code == 404


def test_other_host_names_are_refused(make_app: MakeApp) -> None:
    with served(make_app) as (client, _):
        assert client.get("/", headers={"host": "evil.example"}).status_code == 400


@pytest.mark.parametrize("origin", ["http://evil.example", "http://127.0.0.1:9999", ""])
def test_websockets_from_other_origins_are_refused(make_app: MakeApp, origin: str) -> None:
    with (
        served(make_app) as (client, h),
        pytest.raises(WebSocketDisconnect) as refused,
        tab(client, origin=origin) as ws,
    ):
        ws.receive_json()
    assert refused.value.code == 1008
    assert h.llm.requests == []


def test_a_wrong_token_is_refused_with_a_reason(make_app: MakeApp) -> None:
    with served(make_app) as (client, _), tab(client, token="old-token") as ws:
        with pytest.raises(WebSocketDisconnect) as refused:
            ws.receive_json()
        assert refused.value.code == 1008


def test_hello_then_a_typed_command(make_app: MakeApp, launched: list) -> None:
    script = [reply("", ("open_app", {"name": "notepad"})), reply("Notepad is open.")]
    with served(make_app, script) as (client, h), tab(client) as ws:
        hello = ws.receive_json()
        assert hello["type"] == "hello"
        assert hello["voice"]["enabled"] is False
        ws.send_json({"type": "command", "text": "open notepad"})
        messages = until(ws, "turn_finished")
    kinds = [m["type"] for m in messages]
    assert kinds[0] == "turn_started"
    assert {"tool_call_started", "tool_call_finished", "assistant_message"} <= set(kinds)
    assert messages[0]["source"] == "web"
    reply_message = next(m for m in messages if m["type"] == "assistant_message")
    assert reply_message["text"] == "Notepad is open."
    assert [entry.name for entry in launched] == ["Notepad"]
    assert h.app.history.recent()[0]["source"] == "web"


@pytest.mark.parametrize(("approved", "opened"), [(False, False), (True, True), ("yes", False)])
def test_confirmation_card(make_app: MakeApp, launched: list, approved: Any, opened: bool) -> None:
    script = [reply("", ("open_app", {"name": "spotify"})), reply("ok")]
    with served(make_app, script) as (client, h), tab(client) as ws:
        ws.receive_json()
        ws.send_json({"type": "command", "text": "open spotify"})
        card = until(ws, "confirmation_requested")[-1]
        assert card["request"]["summary"] == "Open Spotify"
        ws.send_json(
            {"type": "confirm", "request_id": card["request"]["request_id"], "approved": approved}
        )
        messages = until(ws, "turn_finished")
    resolved = next(m for m in messages if m["type"] == "confirmation_resolved")
    assert resolved["decision"] == ("confirmed" if opened else "denied")  # only true approves
    assert resolved["via"] == "web"
    assert bool(launched) is opened
    assert h.audit()[0]["confirmed_via"] == ("web" if opened else None)


def test_a_new_tab_sees_the_open_card_and_can_answer(make_app: MakeApp, launched: list) -> None:
    script = [reply("", ("open_app", {"name": "spotify"})), reply("ok")]
    with served(make_app, script) as (client, _), tab(client) as first:
        first.receive_json()
        first.send_json({"type": "command", "text": "open spotify"})
        until(first, "confirmation_requested")
        with tab(client) as second:
            hello = second.receive_json()
            (card,) = hello["open"]
            assert card["type"] == "confirmation_requested"
            second.send_json(
                {"type": "confirm", "request_id": card["request"]["request_id"], "approved": True}
            )
            until(second, "turn_finished")
        until(first, "turn_finished")  # the first tab saw it all too
    assert [entry.name for entry in launched] == ["Spotify"]


def test_stop_button_cancels_and_busy_is_refused(make_app: MakeApp) -> None:
    with served(make_app, [Hang()]) as (client, h), tab(client) as ws:
        ws.receive_json()
        ws.send_json({"type": "command", "text": "think hard"})
        until(ws, "turn_started")
        ws.send_json({"type": "command", "text": "and another thing"})
        assert until(ws, "error")[-1]["message"] == BUSY
        ws.send_json({"type": "stop"})
        finished = until(ws, "turn_finished")[-1]
    assert finished["status"] == "cancelled"
    assert len(h.app.history.recent()) == 1


def test_questions_are_answered_from_the_page(make_app: MakeApp) -> None:
    script = [
        reply("", ("ask_user", {"question": "Which one?", "options": ["Spotify", "Notepad"]})),
        reply("ok"),
    ]
    with served(make_app, script) as (client, h), tab(client) as ws:
        ws.receive_json()
        ws.send_json({"type": "command", "text": "open the music thing"})
        question = until(ws, "question")[-1]
        assert question["options"] == ["Spotify", "Notepad"]
        ws.send_json({"type": "answer", "question_id": question["question_id"], "text": "Spotify"})
        until(ws, "question_closed")
        until(ws, "turn_finished")
    assert h.audit()[0]["result_json"] == '{"answer": "Spotify"}'


def test_voice_turns_show_up_live(make_app: MakeApp) -> None:
    script = [reply("", ("open_app", {"name": "notepad"})), reply("Opened.")]
    with served(make_app, script) as (client, h), tab(client) as ws:
        ws.receive_json()
        assert client.portal is not None
        client.portal.call(h.app.agent.run_turn, "open notepad", "voice")
        messages = until(ws, "turn_finished")
    assert messages[0] == {
        "type": "turn_started",
        "turn_id": messages[0]["turn_id"],
        "text": "open notepad",
        "source": "voice",
    }


def test_audit_mic_and_bad_requests(make_app: MakeApp) -> None:
    script = [reply("", ("open_app", {"name": "notepad"})), reply("ok")]
    with served(make_app, script) as (client, _), tab(client) as ws:
        ws.receive_json()
        ws.send_json({"type": "command", "text": "open notepad"})
        until(ws, "turn_finished")
        ws.send_json({"type": "audit"})
        (row,) = until(ws, "audit")[-1]["rows"]
        assert row["tool"] == "open_app"
        ws.send_json({"type": "mic", "on": True})
        assert until(ws, "error")[-1]["message"] == "Voice is off in this session."
        ws.send_text("not json")
        assert until(ws, "error")[-1]["message"] == "Messages must be JSON."
        ws.send_json({"type": "format_disk"})
        assert "Unknown request" in until(ws, "error")[-1]["message"]


def test_events_keep_their_fields() -> None:
    event = ToolCallStarted(
        turn_id="t", call_id="c", tool="weather", args={"day": "today"}, risk="safe"
    )
    assert event_message(event) == {
        "type": "tool_call_started",
        "turn_id": "t",
        "call_id": "c",
        "tool": "weather",
        "args": {"day": "today"},
        "risk": "safe",
    }


def test_contacts_can_be_added_listed_imported_and_removed(make_app: MakeApp) -> None:
    with served(make_app) as (client, h), tab(client) as ws:
        until(ws, "hello")
        ws.send_json({"type": "contacts"})
        assert until(ws, "contacts")[-1]["contacts"] == []
        ws.send_json(
            {"type": "contact_add", "name": "Amma", "phone": "+91 98765 43210", "aliases": ["Mom"]}
        )
        added = until(ws, "contacts")[-1]
        assert (added["note"], added["added"], added["error"]) == ("Added Amma.", True, False)
        assert added["contacts"][0]["phone"] == "+919876543210"
        ws.send_json({"type": "contact_add", "name": "Amma", "phone": "+91 98765 43211"})
        refused = until(ws, "contacts")[-1]
        assert refused["error"] is True
        assert "already" in refused["note"]
        vcf = "BEGIN:VCARD\nFN:Ravi\nTEL;CELL:+91 90000 00001\nEND:VCARD\n"
        ws.send_json({"type": "contact_import", "text": vcf})
        assert until(ws, "contacts")[-1]["note"] == "Imported 1 contacts."
        amma = h.app.services.contacts.named("Amma")
        ws.send_json({"type": "contact_remove", "id": amma.id})
        assert [c["name"] for c in until(ws, "contacts")[-1]["contacts"]] == ["Ravi"]


def test_contact_requests_are_size_limited(make_app: MakeApp) -> None:
    with served(make_app) as (client, h), tab(client) as ws:
        until(ws, "hello")
        ws.send_json({"type": "contact_add", "name": "A", "phone": "+91 1", "aliases": "Mom"})
        assert until(ws, "contacts")[-1]["error"] is True
        ws.send_json({"type": "contact_import", "text": "x" * 2_000_001})
        assert until(ws, "contacts")[-1]["note"] == "That file is too large."
        assert h.app.services.contacts.all() == []


@pytest.mark.parametrize("speak", [True, False])
def test_typed_replies_are_spoken_when_asked(make_app: MakeApp, speak: bool) -> None:
    hub = WebHub()
    h = make_app(
        [reply("Hello there.")],
        channel=FirstAnswerChannel(WebChannel(hub)),
        overrides={"server": {"speak_replies": speak}},
    )
    runtime = Runtime(h.app, hub)
    server = create_server(runtime, token=TOKEN, port=PORT, hosts=HOSTS)
    with TestClient(server) as client, tab(client) as ws:
        ws.receive_json()
        ws.send_json({"type": "command", "text": "say hi"})
        until(ws, "turn_finished")
        for _ in range(50):
            if h.tts.spoken or not speak:
                break
            time.sleep(0.02)
    assert h.tts.spoken == (["Hello there."] if speak else [])
