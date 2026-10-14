"""The interface every input channel (CLI, voice, web UI) implements to talk back to the user."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ConfirmationRequest:
    request_id: str
    tool: str
    summary: str  # exactly what will happen, for example "Open Spotify"
    digest: str  # hash of the prepared arguments this approval is bound to
    reason: str | None
    timeout_s: float


class UserChannel(Protocol):
    name: str  # recorded in the audit log as the confirming channel

    async def confirm(self, request: ConfirmationRequest) -> bool:
        """Return True only on an explicit yes."""
        ...

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        """Ask a clarifying question and return the answer text."""
        ...
