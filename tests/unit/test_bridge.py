"""The Claude Code bridge: hooks in, your answer out. No real Claude Code, phone, or network."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi.testclient import TestClient

from jarvis.bridge import hook
from jarvis.bridge.answers import match_options, yes_or_no
from jarvis.bridge.phone import NtfyAsker, TwilioAsker
from jarvis.bridge.service import BridgeRequest, BridgeService, publish_address, spoken_question
from jarvis.config import BridgeSettings
from jarvis.server.app import create_server
from jarvis.server.hub import WebHub
from jarvis.server.runtime import Runtime
from tests.conftest import MakeApp

OPTIONS = ["React", "Vue", "Svelte"]
ASK_EVENT = {
    "hook_event_name": "PreToolUse",
    "tool_name": "AskUserQuestion",
    "cwd": "C:/work/shop",
    "tool_input": {
        "questions": [
            {
                "question": "Which framework?",
                "header": "Framework",
                "options": [{"label": o, "description": ""} for o in OPTIONS],
                "multiSelect": False,
            }
        ]
    },
}
BASH_EVENT = {
    "hook_event_name": "PermissionRequest",
    "tool_name": "Bash",
    "cwd": "C:/work/shop",
    "tool_input": {"command": "npm test", "description": "Run tests"},
}


# What you said, matched to an option


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("two", "Vue"),
        ("option two", "Vue"),
        ("the second one", "Vue"),
        ("Vue", "Vue"),
        ("let's go with svelte", "Svelte"),
        ("reakt", "React"),
        ("Svelte", "Svelte"),  # the page sends the label itself
        ("other: use Solid instead", "use Solid instead"),
        ("I want to think about it", None),  # "to" is not "two" here
        ("one and two", None),  # two answers to a one-answer question
        ("banana", None),
    ],
)
def test_answers_match_by_number_or_name(said: str, expected: str | None) -> None:
    assert match_options(said, OPTIONS) == expected


def test_several_answers_when_allowed() -> None:
    assert match_options("one and three", OPTIONS, multi=True) == "React, Svelte"


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("yes", True),
        ("yes please", True),
        ("Allow", True),
        ("allow it", True),
        ("no", False),
        ("Deny", False),
        ("no don't", False),
        ("maybe", None),
        ("", None),
        ("yes no", None),
    ],
)
def test_permissions_need_a_clear_yes_or_no(said: str, expected: bool | None) -> None:
    assert yes_or_no(said) is expected


# Hook events in, hook output out


def test_a_question_becomes_a_bridge_request_and_the_answer_answers_claude() -> None:
    wanted = hook.requests_for(ASK_EVENT)
    assert wanted == [
        {
            "kind": "question",
            "text": "Which framework?",
            "options": OPTIONS,
            "multi": False,
            "project": "shop",
        }
    ]
    out = hook.output_for(ASK_EVENT, [{"answer": "Vue"}])
    assert out is not None
    specific = out["hookSpecificOutput"]
    assert specific["permissionDecision"] == "allow"
    assert specific["updatedInput"]["answers"] == {"Which framework?": "Vue"}
    assert specific["updatedInput"]["questions"] == ASK_EVENT["tool_input"]["questions"]


def test_no_answer_leaves_claude_to_ask() -> None:
    assert hook.output_for(ASK_EVENT, [{}]) is None


def test_permissions_allow_and_deny() -> None:
    assert hook.requests_for(BASH_EVENT)[0]["text"] == "run npm test"
    allow = hook.output_for(BASH_EVENT, [{"allow": True}])
    deny = hook.output_for(BASH_EVENT, [{"allow": False}])
    assert allow == {
        "hookSpecificOutput": {
            "hookEventName": "PermissionRequest",
            "decision": {"behavior": "allow"},
        }
    }
    assert deny is not None
    assert deny["hookSpecificOutput"]["decision"]["behavior"] == "deny"
    assert hook.output_for(BASH_EVENT, [{}]) is None


@pytest.mark.parametrize(
    ("tool", "tool_input", "text"),
    [
        ("Write", {"file_path": "C:/work/shop/app.py"}, "write app.py"),
        ("Edit", {"file_path": "C:/work/shop/app.py"}, "edit app.py"),
        ("WebFetch", {"url": "https://example.com"}, "fetch https://example.com"),
        ("mcp__github__create_issue", {}, "use the create issue tool from github"),
    ],
)
def test_permission_text_is_short_enough_to_say(
    tool: str, tool_input: dict[str, Any], text: str
) -> None:
    assert hook.permission_text(tool, tool_input) == text


def test_plans_and_notices() -> None:
    plan = {**BASH_EVENT, "tool_name": "ExitPlanMode"}
    assert hook.requests_for(plan) == []  # a plan is read, not approved by ear
    waiting = {
        "hook_event_name": "Notification",
        "notification_type": "idle_prompt",
        "cwd": "C:/x/shop",
    }
    assert hook.requests_for(waiting)[0]["text"] == "Claude is waiting for you in shop."
    prompt = {"hook_event_name": "Notification", "notification_type": "permission_prompt"}
    assert hook.requests_for(prompt) == []  # PermissionRequest already asks


def test_run_hook_talks_to_the_running_jarvis(tmp_path: Path) -> None:
    publish_address(tmp_path, 8765)
    token = json.loads((tmp_path / "bridge.json").read_text())["token"]
    seen: list[httpx.Request] = []

    def answer(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"answer": "Svelte"})

    client = httpx.Client(transport=httpx.MockTransport(answer))
    out = json.loads(hook.run_hook(json.dumps(ASK_EVENT), tmp_path, http=client))
    assert out["hookSpecificOutput"]["updatedInput"]["answers"] == {"Which framework?": "Svelte"}
    assert seen[0].url == "http://127.0.0.1:8765/bridge"
    assert seen[0].headers["authorization"] == f"Bearer {token}"


def test_run_hook_is_silent_without_jarvis(tmp_path: Path) -> None:
    assert hook.run_hook(json.dumps(ASK_EVENT), tmp_path) == ""
    assert hook.run_hook("not json", tmp_path) == ""


def test_install_keeps_other_settings_and_uninstall_removes_only_ours(tmp_path: Path) -> None:
    path = tmp_path / "settings.json"
    mine = {"matcher": "Bash", "hooks": [{"type": "command", "command": "my-linter"}]}
    path.write_text(json.dumps({"model": "opus", "hooks": {"PreToolUse": [mine]}}))
    hook.install(path, Path("C:/repo/JARVIS"))
    hook.install(path, Path("C:/repo/JARVIS"))  # twice: still one set
    settings = json.loads(path.read_text())
    assert settings["model"] == "opus"
    assert settings["hooks"]["PreToolUse"][0] == mine
    assert len(settings["hooks"]["PreToolUse"]) == 2
    assert {"PreToolUse", "PermissionRequest", "Notification"} <= set(settings["hooks"])
    assert hook.installed(path)
    assert (tmp_path / "settings.json.jarvis-backup").exists()
    assert hook.uninstall(path)
    assert json.loads(path.read_text())["hooks"] == {"PreToolUse": [mine]}
    assert not hook.installed(path)


# The service inside jarvis serve


def service(*askers: Any, phone: Any = None, **settings: Any) -> tuple[BridgeService, list[str]]:
    spoken: list[str] = []

    async def announce(text: str) -> None:
        spoken.append(text)

    cfg = BridgeSettings(**{"answer_timeout_s": 2, "escalate_after_s": 0.05, **settings})
    return BridgeService(cfg, list(askers), announce, phone=phone), spoken


def reply_with(text: str, delay: float = 0) -> Any:
    async def ask(request: BridgeRequest) -> str:
        await asyncio.sleep(delay)
        return text

    return ask


async def never(request: BridgeRequest) -> str:
    await asyncio.Event().wait()
    return ""


QUESTION = BridgeRequest("question", "Which framework?", OPTIONS, project="shop")
PERMISSION = BridgeRequest("permission", "run npm test", project="shop")


async def test_a_spoken_number_answers() -> None:
    bridge, _ = service(reply_with("two"), never)
    assert await bridge.handle(QUESTION) == {"answer": "Vue"}


async def test_silence_on_one_channel_waits_for_another() -> None:
    bridge, _ = service(reply_with(""), reply_with("Svelte", delay=0.05))
    assert await bridge.handle(QUESTION) == {"answer": "Svelte"}


async def test_no_answer_in_time_means_no_decision() -> None:
    bridge, _ = service(never, answer_timeout_s=0.1)
    assert await bridge.handle(QUESTION) == {}


async def test_an_unclear_permission_answer_is_no_decision() -> None:
    bridge, _ = service(reply_with("hmm maybe"), answer_timeout_s=0.2)
    assert await bridge.handle(PERMISSION) == {}
    bridge, _ = service(reply_with("yes"))
    assert await bridge.handle(PERMISSION) == {"allow": True}
    bridge, _ = service(reply_with("no"))
    assert await bridge.handle(PERMISSION) == {"allow": False}


async def test_settings_can_turn_parts_off() -> None:
    bridge, spoken = service(reply_with("yes"), permissions=False, announce=False)
    assert await bridge.handle(PERMISSION) == {}
    assert await bridge.handle(BridgeRequest("notify", "Claude finished.")) == {}
    assert spoken == []


async def test_notices_are_said() -> None:
    bridge, spoken = service()
    await bridge.handle(BridgeRequest("notify", "Claude is waiting for you in shop."))
    assert spoken == ["Claude is waiting for you in shop."]


async def test_the_phone_joins_after_the_pc_had_its_chance() -> None:
    calls: list[BridgeRequest] = []

    async def phone(request: BridgeRequest) -> str:
        calls.append(request)
        return "Svelte"

    bridge, _ = service(never, phone=phone, escalate_after_s=0.05)
    assert await bridge.handle(QUESTION) == {"answer": "Svelte"}
    bridge, _ = service(reply_with("one"), phone=phone, escalate_after_s=5)
    calls.clear()
    assert await bridge.handle(QUESTION) == {"answer": "React"}
    assert calls == []  # answered at the PC first: the phone never rang


def test_the_spoken_question_numbers_the_options() -> None:
    assert spoken_question(QUESTION) == (
        "Claude in shop asks: Which framework? one, React. two, Vue. three, Svelte. "
        "Say the number or the name."
    )
    assert spoken_question(PERMISSION) == (
        "Claude in shop wants to run npm test. Allow it? Say yes or no."
    )


# The HTTP route


def test_the_route_needs_the_token_and_refuses_browsers(make_app: MakeApp) -> None:
    h = make_app()
    runtime = Runtime(h.app, WebHub())
    runtime.bridge, _ = service(reply_with("one"))
    server = create_server(
        runtime, token="page", port=8765, hosts=("testserver",), bridge_token="secret"
    )
    body = {"kind": "question", "text": "Which framework?", "options": OPTIONS}
    with TestClient(server) as client:
        ok = client.post("/bridge", json=body, headers={"Authorization": "Bearer secret"})
        assert ok.json() == {"answer": "React"}
        assert client.post("/bridge", json=body).status_code == 403
        wrong = client.post("/bridge", json=body, headers={"Authorization": "Bearer nope"})
        assert wrong.status_code == 403
        browser = client.post(
            "/bridge",
            json=body,
            headers={"Authorization": "Bearer secret", "Origin": "https://evil.example"},
        )
        assert browser.status_code == 403
        bad = client.post("/bridge", json={"kind": "x"}, headers={"Authorization": "Bearer secret"})
        assert bad.status_code == 400


# Phones (mocked HTTP)


async def test_ntfy_pushes_buttons_and_reads_the_pressed_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pushed: list[dict[str, Any]] = []

    def server(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            pushed.append(json.loads(request.content))
            return httpx.Response(200, json={"id": "m1"})
        nonce = pushed[0]["actions"][0]["body"].split(":")[0]
        line = json.dumps({"event": "message", "message": f"{nonce}:2"})
        return httpx.Response(200, text=line + "\n")

    http = httpx.AsyncClient(transport=httpx.MockTransport(server))
    asker = NtfyAsker("https://ntfy.example", "jarvis-abc123", None, http)
    monkeypatch.setattr("jarvis.bridge.phone.POLL_S", 0.01)
    assert await asker(QUESTION) == "Svelte"
    assert pushed[0]["priority"] == 5
    assert [a["label"] for a in pushed[0]["actions"]] == OPTIONS
    assert pushed[0]["actions"][0]["url"] == "https://ntfy.example/jarvis-abc123-answers"


async def test_ntfy_never_carries_a_permission_without_a_token() -> None:
    def server(request: httpx.Request) -> httpx.Response:
        raise AssertionError("nothing should be sent")

    http = httpx.AsyncClient(transport=httpx.MockTransport(server))
    assert await NtfyAsker("https://ntfy.example", "t", None, http)(PERMISSION) is None


async def test_twilio_calls_and_reads_the_digit(monkeypatch: pytest.MonkeyPatch) -> None:
    import jarvis.bridge.phone as phone

    monkeypatch.setattr(phone, "POLL_S", 0.01)
    started: list[httpx.Request] = []

    def server(request: httpx.Request) -> httpx.Response:
        if request.method == "POST":
            started.append(request)
            return httpx.Response(201, json={"sid": "FN1"})
        return httpx.Response(200, json={"context": {"widgets": {"ask": {"Digits": "2"}}}})

    http = httpx.AsyncClient(transport=httpx.MockTransport(server))
    asker = TwilioAsker("AC1", "tok", "FW1", "+15550001", "+919876543210", http)
    assert await asker(QUESTION) == "Vue"
    assert started[0].url.path == "/v2/Flows/FW1/Executions"
    assert b"To=%2B919876543210" in started[0].content
    allow = TwilioAsker("AC1", "tok", "FW1", "+1", "+91", http)
    assert yes_or_no(await allow(PERMISSION) or "") is False  # digit 2 is Deny
