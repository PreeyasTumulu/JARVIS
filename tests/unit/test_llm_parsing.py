from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.config import ProviderSettings
from jarvis.llm.client import LLMClient
from jarvis.llm.toolcall_parser import parse_text_tool_calls


def test_parses_closed_tool_call_tags() -> None:
    text = (
        'Sure.\n<tool_call>\n{"name": "open_app", "arguments": {"name": "notepad"}}\n</tool_call>'
    )
    remaining, calls = parse_text_tool_calls(text)
    assert remaining == "Sure."
    assert [(c.name, json.loads(c.arguments)) for c in calls] == [("open_app", {"name": "notepad"})]


def test_parses_unclosed_tag_and_string_arguments() -> None:
    _, calls = parse_text_tool_calls(
        '<tool_call>{"name": "speak", "arguments": "{\\"text\\": \\"hi\\"}"}'
    )
    assert calls[0].name == "speak"
    assert json.loads(calls[0].arguments) == {"text": "hi"}


def test_ignores_malformed_blocks() -> None:
    text = "<tool_call>{nope}</tool_call>"
    assert parse_text_tool_calls(text) == (text, [])


class _FakeCompletions:
    def __init__(self, message: Any) -> None:
        self._message = message
        self.kwargs: dict[str, Any] = {}

    async def create(self, **kwargs: Any) -> Any:
        self.kwargs = kwargs
        return SimpleNamespace(model="m", choices=[SimpleNamespace(message=self._message)])


def _client(message: Any) -> tuple[LLMClient, _FakeCompletions]:
    completions = _FakeCompletions(message)
    fake = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    provider = ProviderSettings(base_url="http://x/v1", model="m")
    return LLMClient(provider, client=fake), completions  # type: ignore[arg-type]


async def test_client_reads_native_tool_calls() -> None:
    call = SimpleNamespace(
        id="call_1", function=SimpleNamespace(name="open_app", arguments='{"name": "x"}')
    )
    client, completions = _client(SimpleNamespace(content=None, tool_calls=[call]))
    result = await client.complete(
        [{"role": "user", "content": "hi"}], tools=[{"type": "function"}]
    )
    assert [(c.id, c.name) for c in result.tool_calls] == [("call_1", "open_app")]
    assert result.parsed_from_text is False
    assert completions.kwargs["tools"] == [{"type": "function"}]


@pytest.mark.parametrize("tools", [None, []])
async def test_client_omits_empty_tools_and_falls_back_to_text(tools: Any) -> None:
    text = '<tool_call>{"name": "speak", "arguments": {"text": "hi"}}</tool_call>'
    client, completions = _client(SimpleNamespace(content=text, tool_calls=None))
    result = await client.complete([], tools=tools)
    assert "tools" not in completions.kwargs
    assert result.parsed_from_text is True
    assert result.tool_calls[0].name == "speak"
    assert result.text == ""
