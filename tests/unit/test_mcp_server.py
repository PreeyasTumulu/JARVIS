"""Jarvis as an MCP server (ADR-085): what is offered, the gate, confirmations, and the endpoint."""

from __future__ import annotations

import json
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from jarvis.server.app import create_server
from jarvis.server.hub import WebHub
from jarvis.server.mcp_server import McpGateway, client_label, offered_tools
from jarvis.server.mcp_stdio import NOT_RUNNING, address, forward, listing
from jarvis.server.runtime import Runtime
from jarvis.tools.catalog import build_registry
from tests.conftest import FakeChannel, Harness, MakeApp

TOKEN = "per-launch-token"
HOSTS = ("testserver", "127.0.0.1", "localhost")
MCP_HEADERS = {
    "authorization": f"Bearer {TOKEN}",
    "accept": "application/json, text/event-stream",
    "content-type": "application/json",
    "x-jarvis-client": "Claude Code",
}


def tools_with(*names: str) -> dict[str, Any]:
    return {"mcp_server": {"tools": list(names)}}


# What is offered


def test_only_listed_public_tools_are_offered() -> None:
    registry = build_registry()
    wanted = ["weather", "send_whatsapp", "read_file", "no_such_tool", "weather", "calculate"]
    assert [t.name for t in offered_tools(registry, wanted)] == ["weather", "calculate"]


def test_the_default_list_is_public_and_harmless(make_app: MakeApp) -> None:
    h = make_app()
    names = [t["name"] for t in McpGateway(h.app.agent).listing()]
    assert names == [
        "weather",
        "calculate",
        "convert_currency",
        "market_data",
        "crypto_price",
        "web_search",
    ]
    calculate = next(t for t in McpGateway(h.app.agent).listing() if t["name"] == "calculate")
    assert calculate["input_schema"]["properties"]["expression"]["type"] == "string"


def test_turned_off_offers_nothing(make_app: MakeApp) -> None:
    h = make_app(overrides={"mcp_server": {"enabled": False}})
    assert McpGateway(h.app.agent).listing() == []


def test_client_names_are_cleaned() -> None:
    assert client_label("Claude Code") == "Claude Code"
    assert client_label("evil\nname<script>") == "evilnamescript"
    assert client_label(None) == "An MCP client"
    assert len(client_label("x" * 200)) == 40


# Calls


async def test_a_call_runs_through_the_gate_and_is_audited(make_app: MakeApp) -> None:
    h = make_app()
    text, failed = await McpGateway(h.app.agent).call(
        "calculate", {"expression": "12 * 7"}, "Claude Code"
    )
    assert not failed
    assert json.loads(text)["summary"] == "84"
    (row,) = h.audit()
    assert (row["tool"], row["decision"], row["handled_by"]) == (
        "calculate",
        "auto",
        "mcp:Claude Code",
    )
    assert h.llm.requests == []  # no model in the loop
    assert h.app.agent.messages == []  # and nothing in the conversation


async def test_a_private_tool_is_refused_even_when_listed(make_app: MakeApp) -> None:
    h = make_app(overrides=tools_with("send_whatsapp", "read_notifications"))
    gateway = McpGateway(h.app.agent)
    assert gateway.listing() == []
    text, failed = await gateway.call(
        "send_whatsapp", {"contact": "Mom", "message": "hi"}, "Claude Code"
    )
    assert failed
    assert "does not offer" in text
    assert h.audit() == []


async def test_bad_arguments_are_refused_by_the_executor(make_app: MakeApp) -> None:
    h = make_app()
    text, failed = await McpGateway(h.app.agent).call("calculate", {"nope": 1}, "Claude Code")
    assert "expression" in text
    assert failed
    assert h.audit()[0]["decision"] == "invalid"


async def test_a_yes_is_asked_on_jarvis_own_channel_naming_the_client(
    make_app: MakeApp, launched: list
) -> None:
    channel = FakeChannel(confirm=False)
    h = make_app(channel=channel, overrides=tools_with("open_app"))
    text, failed = await McpGateway(h.app.agent).call(
        "open_app", {"name": "spotify"}, "Claude Code"
    )
    (request,) = channel.requests
    assert request.summary == "Claude Code wants to: Open Spotify"
    assert failed
    assert "said no" in text
    assert launched == []
    assert h.audit()[0]["decision"] == "denied"


async def test_a_yes_lets_the_call_run(make_app: MakeApp, launched: list) -> None:
    h = make_app(channel=FakeChannel(confirm=True), overrides=tools_with("open_app"))
    _, failed = await McpGateway(h.app.agent).call("open_app", {"name": "spotify"}, "Cursor")
    assert not failed
    assert [entry.name for entry in launched] == ["Spotify"]
    (row,) = h.audit()
    assert (row["decision"], row["confirmed_via"], row["handled_by"]) == (
        "confirmed",
        "test",
        "mcp:Cursor",
    )


# The endpoint on the local API


@contextmanager
def mcp_served(h: Harness) -> Iterator[TestClient]:
    runtime = Runtime(h.app, WebHub())
    app = create_server(runtime, token=TOKEN, hosts=HOSTS, mcp=McpGateway(h.app.agent))
    with TestClient(app) as client:
        yield client


def rpc(client: TestClient, method: str, params: dict[str, Any], **headers: str) -> Any:
    body = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    return client.post("/mcp/", json=body, headers={**MCP_HEADERS, **headers})


def test_the_endpoint_needs_the_token_and_refuses_browsers(make_app: MakeApp) -> None:
    with mcp_served(make_app()) as client:
        assert rpc(client, "tools/list", {}, authorization="Bearer wrong").status_code == 403
        no_token = {k: v for k, v in MCP_HEADERS.items() if k != "authorization"}
        body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
        assert client.post("/mcp/", json=body, headers=no_token).status_code == 403
        browser = rpc(client, "tools/list", {}, origin="https://evil.example")
        assert browser.status_code == 403


def test_the_endpoint_lists_and_calls_tools(make_app: MakeApp) -> None:
    h = make_app()
    with mcp_served(h) as client:
        listed = rpc(client, "tools/list", {})
        assert listed.status_code == 200, listed.text
        names = [t["name"] for t in listed.json()["result"]["tools"]]
        assert "calculate" in names
        assert "send_whatsapp" not in names
        called = rpc(
            client, "tools/call", {"name": "calculate", "arguments": {"expression": "2 + 3"}}
        )
        result = called.json()["result"]
    assert result["isError"] is False
    assert json.loads(result["content"][0]["text"])["summary"] == "5"
    assert h.audit()[0]["handled_by"] == "mcp:Claude Code"


# The stdio command


def test_the_stdio_command_offers_the_same_tools(make_app: MakeApp) -> None:
    h = make_app()
    assert listing(h.app.settings) == McpGateway(h.app.agent).listing()


async def test_the_stdio_command_says_when_jarvis_is_not_running(
    make_app: MakeApp, tmp_path: Path
) -> None:
    h = make_app()
    settings = h.app.settings.model_copy(update={"data_dir": tmp_path})
    assert address(tmp_path) is None
    assert await forward(settings, "calculate", {"expression": "1+1"}, "x") == (NOT_RUNNING, True)
    (tmp_path / "bridge.json").write_text("not json", "utf-8")
    assert address(tmp_path) is None


@pytest.mark.parametrize("raw", ['{"port": 1}', '{"token": "t"}'])
def test_a_broken_address_file_means_not_running(tmp_path: Path, raw: str) -> None:
    (tmp_path / "bridge.json").write_text(raw, "utf-8")
    assert address(tmp_path) is None


async def test_every_channel_sees_who_is_asking(make_app: MakeApp) -> None:
    # The live test found the API's copy of the question without the client's name.
    from jarvis.core.events import ConfirmationRequested

    h = make_app(channel=FakeChannel(confirm=False), overrides=tools_with("open_app"))
    await McpGateway(h.app.agent).call("open_app", {"name": "spotify"}, "Claude Code")
    (event,) = [e for e in h.events if isinstance(e, ConfirmationRequested)]
    assert event.request.summary == "Claude Code wants to: Open Spotify"
    assert event.request.digest  # still bound to the same prepared arguments
