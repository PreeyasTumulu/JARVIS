"""The policy gate: decides whether a prepared tool call is safe, needs confirmation, or is blocked.

The model proposes, the policy decides. Config can raise a tool's risk but never lower it below
the tool's floor or below what the tool's own preparer decided.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import SafetySettings
from jarvis.tools.base import Prepared, Risk
from jarvis.tools.registry import Tool


@dataclass(frozen=True)
class PolicyDecision:
    risk: Risk
    reason: str | None = None


class PolicyGate:
    def __init__(self, safety: SafetySettings) -> None:
        self._safety = safety

    def evaluate(self, tool: Tool, prepared: Prepared) -> PolicyDecision:
        override = self._safety.tool_risk_overrides.get(tool.name, Risk.SAFE)
        built_in = Risk.highest(tool.risk, prepared.risk)
        risk = Risk.highest(built_in, override)
        if override.rank > built_in.rank:
            return PolicyDecision(risk, f"{tool.name} is set to '{override}' in config")
        return PolicyDecision(risk, prepared.reason)


def app_risk(app_name: str, safety: SafetySettings) -> tuple[Risk, str | None]:
    """Risk for opening an app: safe if allowlisted, otherwise confirm or block per config."""
    allowed = {name.casefold() for name in safety.app_allowlist}
    if app_name.casefold() in allowed:
        return Risk.SAFE, None
    reason = f"{app_name} is not in the app allowlist"
    if safety.unlisted_apps == "block":
        return Risk.BLOCKED, reason
    return Risk.CONFIRM, reason
