"""MCP: risk rules, schemas, routing, and a real MCP server over stdio (tests/fixtures).

The notes server is started as a subprocess, so the SDK's stdio transport, the hub's task per
server, and the agent's policy gate are all exercised for real. No network, no account.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from jarvis.config import McpServerSettings, McpSettings
from jarvis.core.tool_routing import select_tools
from jarvis.tools.base import Risk
from jarvis.tools.mcp.hub import McpHub, RemoteTool, expand, missing_vars
from jarvis.tools.mcp.tools import args_model, risk_for, tool_name
from tests.conftest import FakeChannel, MakeApp, reply

NOTES_SERVER = Path(__file__).resolve().parents[1] / "fixtures" / "mcp_notes_server.py"
LISTED = ["list_notes", "add_note", "delete_notes", "fail"]


def notes(**changes: Any) -> McpServerSettings:
    values: dict[str, Any] = {
        "command": sys.executable,
        "args": [str(NOTES_SERVER)],
        "tools": LISTED,
        "trusted": True,
        "keywords": ["note", "notes"],
        "label": "Notes",
    }
    values.update(changes)
    return McpServerSettings(**values)


async def with_notes(h: Any, tmp_path: Path, **changes: Any) -> list[str]:
    h.app.services.mcp = McpHub(
        McpSettings(servers={"notes": notes(**changes)}, connect_timeout_s=30), log_dir=tmp_path
    )
    return await h.app.agent.prepare_tools()


def remote(read_only: bool) -> RemoteTool:
    return RemoteTool(
        "s", "t", "d", {}, read_only=read_only, destructive=not read_only, open_world=True
    )


@pytest.mark.parametrize(
    ("read_only", "trusted", "override", "expected"),
    [
        (True, True, None, Risk.SAFE),
        (True, False, None, Risk.CONFIRM),  # an untrusted server's labels are not believed
        (False, True, None, Risk.CONFIRM),
        (True, True, Risk.CONFIRM, Risk.CONFIRM),  # config can raise
        (True, True, Risk.BLOCKED, Risk.BLOCKED),
        (False, True, Risk.SAFE, Risk.CONFIRM),  # but never lower
    ],
)
def test_risk_rules(read_only: bool, trusted: bool, override: Risk | None, expected: Risk) -> None:
    server = notes(trusted=trusted, risk={"t": override} if override else {})
    assert risk_for(remote(read_only), server) is expected


def test_names_and_schemas() -> None:
    assert tool_name("home assistant", "turn.on") == "home_assistant_turn_on"
    assert len(tool_name("x" * 40, "y" * 40)) == 64
    model = args_model(
        "t",
        {"type": "object", "properties": {"owner": {"type": "string"}, "n": {"type": "integer"}},
         "required": ["owner"]},
    )  # fmt: skip
    assert model.model_validate({"owner": "me"}).model_dump() == {"owner": "me", "n": None}
    with pytest.raises(ValidationError):
        model.model_validate({"n": 3})


def test_secrets_come_from_the_environment() -> None:
    env = {"GITHUB_TOKEN": "t0k"}
    assert expand("Bearer $GITHUB_TOKEN", env) == "Bearer t0k"
    assert expand("${GITHUB_TOKEN}", env) == "t0k"
    server = McpServerSettings(url="https://x.example/mcp", headers={"Authorization": "$NOPE"})
    assert missing_vars(server, env) == ["NOPE"]


def test_a_server_needs_exactly_one_transport() -> None:
    with pytest.raises(ValidationError):
        McpServerSettings(command="x", url="https://x.example")
    with pytest.raises(ValidationError):
        McpServerSettings()


async def test_only_listed_tools_are_registered(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app()
    added = await with_notes(h, tmp_path)
    assert sorted(added) == [
        "notes_add_note",
        "notes_delete_notes",
        "notes_fail",
        "notes_list_notes",
    ]
    assert h.app.registry.get("notes_secret_tool") is None
    listed = h.app.registry.get("notes_list_notes")
    assert listed is not None
    assert listed.risk is Risk.SAFE
    assert listed.untrusted
    assert listed.sensitivity.value == "private"
    assert listed.description.startswith("[Notes] List the saved notes")
    assert listed.schema()["function"]["parameters"]["properties"]["contains"]["type"] == "string"
    await h.app.services.mcp.aclose()


async def test_a_read_only_tool_runs_and_its_result_is_data(
    make_app: MakeApp, tmp_path: Path
) -> None:
    h = make_app([reply("", ("notes_list_notes", {})), reply("You have one note: buy milk.")])
    await with_notes(h, tmp_path)
    result = await h.app.agent.run_turn("what's in my notes")
    outcome = result.outcomes[0]
    assert outcome.decision.value == "auto"
    assert outcome.result.data == {"server": "Notes", "result": "buy milk"}
    assert 'untrusted="true"' in outcome.model_content(10_000)
    assert h.channel.requests == []
    await h.app.services.mcp.aclose()


async def test_a_writing_tool_asks_and_no_means_no(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app(
        [
            reply("", ("notes_add_note", {"text": "call mom"})),
            reply("", ("notes_list_notes", {})),
            reply("Okay."),
        ],
        channel=FakeChannel(confirm=False),
    )
    await with_notes(h, tmp_path)
    result = await h.app.agent.run_turn("add a note to call mom")
    assert h.channel.requests[0].summary == "Notes: add note (text: call mom)"
    assert result.outcomes[0].decision.value == "denied"
    assert result.outcomes[1].result.data["result"] == "buy milk"  # nothing was added
    await h.app.services.mcp.aclose()


async def test_an_untrusted_server_asks_even_to_read(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app([reply("", ("notes_list_notes", {})), reply("Done.")])
    await with_notes(h, tmp_path, trusted=False)
    result = await h.app.agent.run_turn("read my notes")
    assert result.outcomes[0].decision.value == "confirmed"
    assert len(h.channel.requests) == 1
    await h.app.services.mcp.aclose()


async def test_safety_overrides_can_block_an_mcp_tool(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app(
        [reply("", ("notes_delete_notes", {})), reply("I can't.")],
        overrides={"safety": {"tool_risk_overrides": {"notes_delete_notes": "blocked"}}},
    )
    await with_notes(h, tmp_path)
    result = await h.app.agent.run_turn("delete all my notes")
    assert result.outcomes[0].decision.value == "blocked"
    assert h.channel.requests == []
    await h.app.services.mcp.aclose()


async def test_a_server_error_is_reported(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app([reply("", ("notes_fail", {})), reply("It failed.")], channel=FakeChannel())
    await with_notes(h, tmp_path, risk={})
    result = await h.app.agent.run_turn("run the notes fail tool")
    assert not result.outcomes[0].result.ok
    assert result.outcomes[0].result.error.startswith("Notes said:")
    await h.app.services.mcp.aclose()


async def test_a_server_without_its_secret_is_skipped(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app([reply("Hello.")])
    added = await with_notes(h, tmp_path, env={"TOKEN": "$JARVIS_TEST_MISSING_TOKEN"})
    assert added == []
    assert (await h.app.agent.run_turn("hello")).text == "Hello."


async def test_a_broken_server_does_not_break_jarvis(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app([reply("Hello.")])
    added = await with_notes(h, tmp_path, args=[str(tmp_path / "missing_server.py")])
    assert added == []
    assert h.app.services.mcp.servers["notes"].error
    assert (await h.app.agent.run_turn("hello")).text == "Hello."
    await h.app.services.mcp.aclose()


async def test_mcp_tools_are_offered_only_by_their_keywords(
    make_app: MakeApp, tmp_path: Path
) -> None:
    h = make_app()
    await with_notes(h, tmp_path)
    registry = h.app.registry
    offered = {t.name for t in select_tools("add a note to buy eggs", registry)}
    assert "notes_add_note" in offered
    assert "open_app" not in offered
    assert not {t.name for t in select_tools("open notepad", registry)} & {"notes_add_note"}
    unmatched = {t.name for t in select_tools("blorp zing", registry)}  # everything built in
    assert "open_app" in unmatched
    assert "notes_add_note" not in unmatched
    await h.app.services.mcp.aclose()


async def test_listing_every_offered_tool(tmp_path: Path) -> None:
    hub = McpHub(McpSettings(servers={"notes": notes()}, connect_timeout_s=30), log_dir=tmp_path)
    offered = {t.name: t for t in await hub.offered("notes")}
    assert set(offered) == {*LISTED, "secret_tool"}
    assert offered["list_notes"].read_only
    assert not offered["add_note"].read_only


def test_schemas_are_compacted_but_keep_every_parameter_name() -> None:
    from jarvis.tools.mcp.tools import compact_schema

    schema = {
        "type": "object",
        "$schema": "http://json-schema.org/draft-07/schema#",
        "properties": {
            "title": {"type": "string", "title": "Title", "description": "x" * 300},
            "owner": {"type": "string", "x-mcp-header": "owner"},
            "fields": {"type": "array", "items": {"type": "object", "properties": {"a": {}}}},
            "page": {"type": "integer", "default": 1},
        },
        "required": ["owner"],
    }
    full = compact_schema(schema, None)
    assert set(full["properties"]) == {"title", "owner", "fields", "page"}
    assert "$schema" not in full
    assert "title" not in full["properties"]["title"]
    assert len(full["properties"]["title"]["description"]) == 100
    assert full["properties"]["owner"] == {"type": "string"}
    assert full["properties"]["fields"]["items"] == {"type": "object"}
    assert "default" not in full["properties"]["page"]
    kept = compact_schema(schema, ["title"])
    assert set(kept["properties"]) == {"title", "owner"}  # required ones always stay
