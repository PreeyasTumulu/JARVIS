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
    hint: str | None = None  # Jarvis's own note to the model, kept outside untrusted content

    @classmethod
    def success(
        cls, data: Any = None, speech: str | None = None, hint: str | None = None
    ) -> ToolResult:
        return cls(ok=True, data=data, speech=speech, hint=hint)

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
        return args_digest(self.args)


def args_digest(args: dict[str, Any]) -> str:
    payload = json.dumps(args, sort_keys=True, default=str)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


_SEAL = object()  # only `issue_clearance` holds it; tools/policy.py is its only caller


class Clearance:
    """Permission from the policy gate to run one tool once, with exactly the approved arguments.

    A tool refuses to run without one (Tool.__call__), so no code path can skip the gate:
    the fast path, the model, the cloud, and later the MCP server all reach tools the same way.
    """

    __slots__ = ("_seal", "decision", "digest", "risk", "spent", "tool")

    def __init__(self, tool: str, digest: str, risk: Risk, decision: str, seal: object) -> None:
        self.tool = tool
        self.digest = digest
        self.risk = risk
        self.decision = decision
        self.spent = False
        self._seal = seal

    def spend(self, tool: str, args: dict[str, Any]) -> None:
        """Use the clearance up. Raises PermissionError if it does not cover this call."""
        if self._seal is not _SEAL:
            raise PermissionError(f"{tool} was not cleared by the policy gate")
        if self.spent:
            raise PermissionError(f"The clearance for {tool} was already used")
        if self.tool != tool or self.digest != args_digest(args):
            raise PermissionError(f"The clearance does not cover this call of {tool}")
        self.spent = True


def issue_clearance(tool: str, args: dict[str, Any], risk: Risk, decision: str) -> Clearance:
    """Called only by PolicyGate.clear (a test checks no other module calls it)."""
    return Clearance(tool, args_digest(args), risk, decision, _SEAL)


@dataclass(frozen=True)
class ContextFlags:
    """What the model's context holds right now, for rules that depend on it (see policy.py)."""

    private: bool = False  # output of a private tool: files, clipboard, answers, logs
    untrusted: bool = False  # outside content that could carry instructions: pages, file text


@dataclass
class ToolContext:
    settings: Settings
    channel: UserChannel
    services: Services
    session_id: str
    turn_id: str
    flags: ContextFlags = ContextFlags()
    handled_by: str = "agent"  # the router stage that produced this turn's calls (ADR-083)
    requester: str | None = None  # another program asking (an MCP client), named in questions
