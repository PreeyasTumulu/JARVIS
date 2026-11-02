"""Fallback parser for Hermes-style tool calls that arrive as plain text.

Ollama normally converts Hermes 3's `<tool_call>{...}</tool_call>` output into structured
`tool_calls`. If a template or version mismatch leaves the tags in the text, this recovers them.
The model also sometimes writes a call as a whole reply of bare JSON, with "name" or "function"
as the key, which would otherwise be read aloud. Either way the call still goes through the gate.
"""

from __future__ import annotations

import json
import re
import uuid

from jarvis.llm.types import ToolCall

_CLOSED = re.compile(r"<tool_call>\s*(\{.*?\})\s*</tool_call>", re.DOTALL)
_UNCLOSED = re.compile(r"<tool_call>\s*(\{.*\})\s*$", re.DOTALL)
_BARE = re.compile(r"^\s*(?:```(?:json)?\s*)?(\{.*\})\s*(?:```)?\s*$", re.DOTALL)


def parse_text_tool_calls(text: str) -> tuple[str, list[ToolCall]]:
    """Return (text without tool-call tags, parsed calls). Malformed blocks are ignored."""
    pattern = _CLOSED if _CLOSED.search(text) else _UNCLOSED
    calls: list[ToolCall] = []
    for match in pattern.finditer(text):
        call = _to_tool_call(match.group(1))
        if call is not None:
            calls.append(call)
    if calls:
        return pattern.sub("", text).strip(), calls
    bare = _BARE.match(text)
    call = _to_tool_call(bare.group(1), needs_arguments=True) if bare else None
    return ("", [call]) if call is not None else (text, [])


def _to_tool_call(raw: str, *, needs_arguments: bool = False) -> ToolCall | None:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    name = payload.get("name", payload.get("function"))
    if not isinstance(name, str) or (needs_arguments and "arguments" not in payload):
        return None
    arguments = payload.get("arguments", {})
    if not isinstance(arguments, str):
        arguments = json.dumps(arguments, ensure_ascii=False)
    return ToolCall(id=f"call_{uuid.uuid4().hex[:12]}", name=name, arguments=arguments)
