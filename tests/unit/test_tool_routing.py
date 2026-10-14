from __future__ import annotations

import pytest

from jarvis.core.tool_routing import select_tools
from jarvis.tools.catalog import build_registry
from tests.conftest import MakeApp, reply

REGISTRY = build_registry()


def names(text: str) -> set[str]:
    return {tool.name for tool in select_tools(text, REGISTRY)}


def test_docker_requests_get_docker_tools() -> None:
    chosen = names("stop the postgres container")
    assert {"docker_stop", "docker_list", "ask_user", "speak"} <= chosen
    assert "find_file" not in chosen


def test_file_requests_get_file_tools() -> None:
    chosen = names("what is this file")
    assert {"get_selected_file", "read_file", "find_file"} <= chosen
    assert "docker_stop" not in chosen


@pytest.mark.parametrize("text", ["hi jarvis", "thanks", "tell me a joke"])
def test_unmatched_requests_get_every_tool(text: str) -> None:
    assert names(text) == set(REGISTRY.names())


def test_open_by_name_gets_apps_and_files() -> None:
    chosen = names("open the jarvis readme")
    assert {"open_app", "find_file", "open_file"} <= chosen


async def test_agent_sends_routed_tools(make_app: MakeApp) -> None:
    h = make_app([reply("No containers.")])
    await h.app.agent.run_turn("list my docker containers")
    offered = {t["function"]["name"] for t in h.llm.tools_seen[0] or []}
    assert "docker_list" in offered
    assert "web_search" not in offered


async def test_routing_can_be_turned_off(make_app: MakeApp) -> None:
    h = make_app([reply("ok")], overrides={"agent": {"tool_routing": "all"}})
    await h.app.agent.run_turn("list my docker containers")
    assert len(h.llm.tools_seen[0] or []) == len(REGISTRY)
