"""Types shared by every tool: risk levels, sensitivity labels, results, and the call context."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel

if TYPE_CHECKING:
    from jarvis.config import Settings
    from jarvis.core.channel import UserChannel
    from jarvis.services import Services


class Risk(StrEnum):
    """How much permission a tool call needs. Ordered: safe < confirm < blocked."""

    SAFE = "safe"
    CONFIRM = "confirm"
    BLOCKED = "blocked"

    @property
    def rank(self) -> int:
        return _RISK_RANK[self]

    @staticmethod
    def highest(*levels: Risk) -> Risk:
        return max(levels, key=lambda level: level.rank)


_RISK_RANK = {Risk.SAFE: 0, Risk.CONFIRM: 1, Risk.BLOCKED: 2}


class Sensitivity(StrEnum):
    """Whether a tool result may ever be shown to a cloud model."""

    PUBLIC = "public"
    PRIVATE = "private"

    @staticmethod
    def highest(*levels: Sensitivity) -> Sensitivity:
        return Sensitivity.PRIVATE if Sensitivity.PRIVATE in levels else Sensitivity.PUBLIC


class ToolError(Exception):
    """An expected tool failure. The message is shown to the model and the user."""


class ToolResult(BaseModel):
    ok: bool
    data: Any = None
    speech: str | None = None
    error: str | None = None

    @classmethod
    def success(cls, data: Any = None, speech: str | None = None) -> ToolResult:
        return cls(ok=True, data=data, speech=speech)

    @classmethod
    def failure(cls, error: str) -> ToolResult:
        return cls(ok=False, error=error)


@dataclass(frozen=True)
class Prepared:
    """A validated, resolved tool call that has not run yet.

    `args` are canonical (for example a fuzzy app name resolved to its exact name), and they are
    exactly what runs after approval. `summary` is what the user is asked to confirm.
    """

    args: dict[str, Any]
    summary: str
    risk: Risk = Risk.SAFE
    reason: str | None = None

    @property
    def digest(self) -> str:
        payload = json.dumps(self.args, sort_keys=True, default=str)
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass
class ToolContext:
    settings: Settings
    channel: UserChannel
    services: Services
    session_id: str
    turn_id: str
