from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolResult
from jarvis.tools.catalog import build_registry
from jarvis.tools.registry import Registry, parse_docstring, tool


@tool(risk=Risk.CONFIRM)
async def sample(
    ctx: ToolContext, city: str, days: int = 3, tags: list[str] | None = None
) -> ToolResult:
    """Get a forecast for a city.

    Extra detail on a second line.

    Args:
        city: The city name,
            possibly with a country.
        days: How many days ahead.
        tags: Optional labels.

    Returns:
        Nothing useful.
    """
    return ToolResult.success({"city": city, "days": days})


def test_schema_comes_from_signature_and_docstring() -> None:
    schema = sample.schema()
    fn = schema["function"]
    assert schema["type"] == "function"
    assert fn["name"] == "sample"
    assert fn["description"] == "Get a forecast for a city. Extra detail on a second line."
    params = fn["parameters"]
    assert params["required"] == ["city"]
    assert params["properties"]["city"]["description"] == "The city name, possibly with a country."
    assert params["properties"]["days"]["default"] == 3
    assert "title" not in json.dumps(params)


def test_defaults_are_private_and_risk_is_kept() -> None:
    assert sample.risk is Risk.CONFIRM
    assert sample.sensitivity is Sensitivity.PRIVATE
    assert sample.untrusted is False


def test_validation_coerces_and_rejects() -> None:
    assert sample.validate({"city": "Pune", "days": "2", "extra": 1}) == {
        "city": "Pune",
        "days": 2,
        "tags": None,
    }
    with pytest.raises(ValidationError):
        sample.validate({"days": 2})


async def test_default_prepare_uses_tool_risk() -> None:
    prepared = await sample.prepare(None, {"city": "Pune"})  # type: ignore[arg-type]
    assert prepared.risk is Risk.CONFIRM
    assert prepared.summary == "sample(city='Pune')"
    assert len(prepared.digest) == 16


def test_decorator_rejects_bad_tools() -> None:
    with pytest.raises(TypeError):

        @tool(risk=Risk.SAFE)
        def not_async(ctx: ToolContext) -> ToolResult:  # type: ignore[arg-type]
            """Sync."""
            return ToolResult.success()

    with pytest.raises(ValueError, match="docstring"):

        @tool(risk=Risk.SAFE)
        async def undocumented(ctx: ToolContext) -> ToolResult:
            return ToolResult.success()


def test_registry_rejects_duplicates() -> None:
    with pytest.raises(ValueError, match="already registered"):
        Registry([sample, sample])


def test_parse_docstring_without_args() -> None:
    assert parse_docstring("Just one line.") == ("Just one line.", {})
    assert parse_docstring(None) == ("", {})


ALL_TOOLS = {
    "open_app", "focus_app", "close_app", "find_file", "open_file", "read_file",
    "get_selected_file", "vscode_open", "docker_list", "docker_logs", "docker_start",
    "docker_stop", "web_search", "search_site", "open_url", "fetch_page", "market_data",
    "crypto_price",
    "convert_currency", "weather", "set_volume", "set_brightness", "lock_screen", "screenshot",
    "clipboard_read", "clipboard_write", "set_timer", "set_reminder", "list_reminders",
    "cancel_reminder", "type_text", "click", "press_keys", "read_window_text", "browser_open",
    "browser_read", "browser_click", "browser_type", "send_whatsapp", "call_contact",
    "media_control", "now_playing", "read_notifications",
    "remember", "list_memories", "forget",
    "speak", "ask_user",
}  # fmt: skip


def test_shipped_tools_have_clean_schemas() -> None:
    registry = build_registry()
    assert set(registry.names()) == ALL_TOOLS
    for item in registry:
        schema = item.schema()["function"]
        assert schema["description"]
        for name, prop in schema["parameters"]["properties"].items():
            assert prop.get("description"), f"{item.name}.{name} has no description"
        json.dumps(schema)


def test_send_whatsapp_always_asks_and_the_browser_counts_as_egress() -> None:
    registry = build_registry()
    send = registry.get("send_whatsapp")
    assert send is not None
    assert send.risk is Risk.CONFIRM
    assert send.sensitivity is Sensitivity.PRIVATE
    egress = {tool.name for tool in registry if tool.egress}
    assert egress == {
        "fetch_page",
        "browser_open",
        "browser_type",
        "web_search",
        "open_url",
        "search_site",
    }
    read = registry.get("read_window_text")
    assert read is not None
    assert read.untrusted
    assert read.sensitivity is Sensitivity.PRIVATE


def test_the_word_null_for_an_optional_argument_means_none() -> None:
    from jarvis.tools.catalog import build_registry

    registry = build_registry()
    type_text = registry.get("type_text")
    assert type_text is not None
    args = type_text.validate({"app": "notepad", "text": "hi", "field": "null"})
    assert args["field"] is None
    assert type_text.validate({"app": "notepad", "text": "None", "field": "x"})["text"] == "None"
