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


def test_shipped_tools_have_clean_schemas() -> None:
    registry = build_registry()
    assert registry.names() == ["open_app", "web_search", "speak", "ask_user"]
    for item in registry:
        schema = item.schema()["function"]
        assert schema["description"]
        for name, prop in schema["parameters"]["properties"].items():
            assert prop.get("description"), f"{item.name}.{name} has no description"
        json.dumps(schema)
