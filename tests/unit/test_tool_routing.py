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


@pytest.mark.parametrize(
    "text",
    [
        "message mom that I'll be late",
        "tell Ravi that the meeting moved",
        "send a whatsapp to dad saying hi",
        "let Priya know I reached",
    ],
)
def test_messages_get_send_whatsapp(text: str) -> None:
    assert "send_whatsapp" in names(text)


@pytest.mark.parametrize(
    "text",
    [
        "type hello world in notepad",
        "click save in notepad",
        "press ctrl s",
        "what does notepad say",
    ],
)
def test_ui_requests_get_ui_tools(text: str) -> None:
    assert {"type_text", "click", "press_keys", "read_window_text"} <= names(text)


def test_working_in_a_website_gets_browser_tools() -> None:
    chosen = names("search for headphones on amazon")
    assert {"browser_open", "browser_type", "browser_click"} <= chosen
    assert "send_whatsapp" not in chosen


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


@pytest.mark.parametrize(
    ("text", "expected", "absent"),
    [
        ("what's reliance trading at", {"market_data"}, {"web_search"}),
        ("bitcoin in rupees", {"crypto_price"}, {"web_search"}),
        ("convert 100 dollars to rupees", {"convert_currency"}, {"web_search"}),
        ("what's the weather tomorrow", {"weather"}, {"web_search"}),
        ("volume to 30", {"set_volume"}, {"weather"}),
        ("lock my laptop", {"lock_screen"}, {"market_data"}),
        ("take a screenshot", {"screenshot"}, {"web_search"}),
        ("remind me in 10 minutes to stretch", {"set_reminder", "set_timer"}, {"web_search"}),
        ("summarize this article https://example.com/a", {"fetch_page"}, set()),
        ("who won the cricket world cup", {"web_search"}, {"open_app"}),
    ],
)
def test_phase4_groups(text: str, expected: set[str], absent: set[str]) -> None:
    chosen = names(text)
    assert expected <= chosen
    assert not absent & chosen


def test_speech_requests_get_only_speak() -> None:
    assert names("announce that the meeting starts in five minutes") == {"speak", "ask_user"}
