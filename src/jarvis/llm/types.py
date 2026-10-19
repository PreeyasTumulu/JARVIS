"""Plain data types for model replies, independent of any provider SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str  # raw JSON text exactly as the model produced it

    def as_message_part(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "type": "function",
            "function": {"name": self.name, "arguments": self.arguments},
        }


@dataclass(frozen=True)
class LLMReply:
    text: str
    model: str
    latency_ms: int
    tool_calls: list[ToolCall] = field(default_factory=list)
    parsed_from_text: bool = False  # True if tool calls came from the <tool_call> text fallback
    prompt_tokens: int = 0
    completion_tokens: int = 0


class LLMError(Exception):
    """The model server could not produce a reply. The message is safe to show the user."""


class ChatModel(Protocol):
    """What the agent needs from a model. LLMClient implements it; tests use a scripted fake."""

    @property
    def model(self) -> str: ...

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMReply: ...

    async def check(self) -> str | None: ...

    async def aclose(self) -> None: ...
