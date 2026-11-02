"""The policy gate: decides whether a prepared tool call is safe, needs confirmation, or is blocked.

The model proposes, the policy decides. Config can raise a tool's risk but never lower it below
the tool's floor or below what the tool's own preparer decided.

One rule depends on the conversation rather than the call: when private data and outside content
are both in the model's context, a tool that sends a request to an address the model picks
(`egress`) needs confirmation. Those three together are what a prompt injection needs to leak
data, for example a web page telling the model to fetch `https://evil.example/?q=<your file>`.
"""

from __future__ import annotations

from dataclasses import dataclass

from jarvis.config import SafetySettings
from jarvis.tools.base import ContextFlags, Prepared, Risk
from jarvis.tools.registry import Tool

EXFILTRATION_REASON = (
    "private data and outside content are both in this conversation, and this sends a "
    "request to the internet"
)


@dataclass(frozen=True)
class PolicyDecision:
    risk: Risk
    reason: str | None = None


class PolicyGate:
    def __init__(self, safety: SafetySettings) -> None:
        self._safety = safety

    def evaluate(
        self, tool: Tool, prepared: Prepared, flags: ContextFlags | None = None
    ) -> PolicyDecision:
        override = self._safety.tool_risk_overrides.get(tool.name, Risk.SAFE)
        built_in = Risk.highest(tool.risk, prepared.risk)
        reason = prepared.reason
        if (
            tool.egress
            and flags is not None
            and flags.private
            and flags.untrusted
            and built_in.rank < Risk.CONFIRM.rank
        ):
            built_in, reason = Risk.CONFIRM, EXFILTRATION_REASON
        risk = Risk.highest(built_in, override)
        if override.rank > built_in.rank:
            return PolicyDecision(risk, f"{tool.name} is set to '{override}' in config")
        return PolicyDecision(risk, reason)


def app_risk(app_name: str, safety: SafetySettings) -> tuple[Risk, str | None]:
    """Risk for opening an app: safe if allowlisted, otherwise confirm or block per config."""
    allowed = {name.casefold() for name in safety.app_allowlist}
    if app_name.casefold() in allowed:
        return Risk.SAFE, None
    reason = f"{app_name} is not in the app allowlist"
    if safety.unlisted_apps == "block":
        return Risk.BLOCKED, reason
    return Risk.CONFIRM, reason
