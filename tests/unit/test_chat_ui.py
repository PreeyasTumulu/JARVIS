"""The chat window served by jarvis serve (ADR-103): only this page may use the socket."""

from __future__ import annotations

import re
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from jarvis.core.channel import FirstAnswerChannel
from jarvis.core.fast_path import exact_call
from jarvis.llm.types import ToolCall
from jarvis.server import ui
from jarvis.server.app import create_server
from jarvis.server.hub import WebChannel, WebHub
from jarvis.server.runtime import Runtime
from jarvis.tools import chat_window
from jarvis.tools.base import ToolContext
from tests.conftest import Harness, MakeApp

ROOT = Path(__file__).resolve().parents[2]
TOKEN = "per-launch-token"
UI = "the-chat-pages-own-token-0123456789"
PORT = 8765
HOSTS = ("testserver", "127.0.0.1", "localhost")
PAGE = f"http://127.0.0.1:{PORT}"


@contextmanager
def served(make_app: MakeApp) -> Iterator[tuple[TestClient, Harness]]:
    hub = WebHub()
    h = make_app(channel=FirstAnswerChannel(WebChannel(hub)))
    runtime = Runtime(h.app, hub)
    server = create_server(runtime, token=TOKEN, hosts=HOSTS, ui_token=UI, port=PORT)
    with TestClient(server) as client:
        yield client, h


def tab(client: TestClient, token: str, origin: str | None) -> Any:
    headers = {"origin": origin} if origin is not None else {}
    return client.websocket_connect(f"/ws?token={token}", headers=headers)


def test_the_page_carries_its_token_and_a_strict_policy(make_app: MakeApp) -> None:
    with served(make_app) as (client, _):
        response = client.get("/", headers={"sec-fetch-site": "none"})
    assert response.status_code == 200
    html = response.text
    assert f'"token": "{UI}"' in html
    assert TOKEN not in html  # the programs' token never reaches a page
    policy = response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in policy
    assert response.headers["x-frame-options"] == "DENY"
    nonce = re.search(r"script-src 'nonce-([\w-]+)'", policy)
    assert nonce is not None
    scripts = re.findall(r"<script([^>]*)>", html)
    assert scripts
    assert all(f'nonce="{nonce[1]}"' in attrs for attrs in scripts)
    assert f"connect-src ws://127.0.0.1:{PORT} ws://localhost:{PORT}" in policy
    assert "unsafe-eval" not in policy


@pytest.mark.parametrize("site", ["cross-site", "same-site"])
def test_other_sites_cannot_fetch_the_page(make_app: MakeApp, site: str) -> None:
    with served(make_app) as (client, _):
        assert client.get("/", headers={"sec-fetch-site": site}).status_code == 403
        assert client.get("/", headers={"origin": "https://evil.example"}).status_code == 403


def test_the_page_may_open_the_socket(make_app: MakeApp) -> None:
    with served(make_app) as (client, _), tab(client, UI, PAGE) as ws:
        hello = ws.receive_json()
    assert hello["type"] == "hello"


@pytest.mark.parametrize(
    ("token", "origin"),
    [
        (UI, "https://evil.example"),  # a website that somehow learned the page's token
        (UI, f"http://127.0.0.1:{PORT + 1}"),  # another local page
        (UI, "null"),  # a file opened from disk
        (TOKEN, PAGE),  # the programs' token is never accepted from a browser
        (UI, None),  # and a program needs the programs' token
    ],
)
def test_everything_else_is_refused(make_app: MakeApp, token: str, origin: str | None) -> None:
    with (
        served(make_app) as (client, _),
        pytest.raises(WebSocketDisconnect),
        tab(client, token, origin) as ws,
    ):
        ws.receive_json()


def test_without_a_ui_token_there_is_no_page(make_app: MakeApp) -> None:
    hub = WebHub()
    h = make_app(channel=FirstAnswerChannel(WebChannel(hub)))
    with TestClient(create_server(Runtime(h.app, hub), token=TOKEN, hosts=HOSTS)) as client:
        assert client.get("/").status_code == 404


def test_the_ui_token_survives_a_restart(tmp_path: Path) -> None:
    first = ui.ui_token(tmp_path)
    assert len(first) >= 24
    assert ui.ui_token(tmp_path) == first
    (tmp_path / "ui_token").write_text("short", "utf-8")
    assert ui.ui_token(tmp_path) != "short"


def test_brave_opens_it_as_an_app_window(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    brave = tmp_path / "brave.exe"
    brave.write_text("", "utf-8")
    monkeypatch.setattr(ui, "default_browser", lambda: "brave")
    monkeypatch.setattr(ui, "find_brave", lambda: brave)
    command = ui.browser_command(ui.url(PORT))
    assert command == [str(brave), f"--app=http://127.0.0.1:{PORT}/", "--window-size=480,800"]


def test_the_served_page_is_the_chat_demo() -> None:
    served_page = ROOT / "src" / "jarvis" / "server" / "ui" / "chat.html"
    assert served_page.read_bytes() == (ROOT / "ui-demos" / "chat.html").read_bytes()
    assert ui.LIVE_MARKER in served_page.read_text("utf-8")


def test_open_jarvis_is_an_exact_phrase() -> None:
    assert exact_call("open Jarvis") == ("open_chat", "{}")
    assert exact_call("show the chat") == ("open_chat", "{}")


async def test_open_chat_needs_serve_and_opens_the_window(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = make_app()
    ctx = ToolContext(h.app.settings, h.channel, h.app.services, "s", "t")
    call = ToolCall("c1", "open_chat", "{}")
    monkeypatch.setattr(chat_window, "running_port", lambda _: None)
    outcome = await h.app.agent.executor.run(call, ctx)
    assert not outcome.result.ok
    assert "jarvis serve" in outcome.result.error
    opened: list[int] = []
    monkeypatch.setattr(chat_window, "running_port", lambda _: PORT)
    monkeypatch.setattr(chat_window, "open_window", lambda port: opened.append(port) or "brave")
    outcome = await h.app.agent.executor.run(call, ctx)
    assert outcome.result.ok
    assert opened == [PORT]
