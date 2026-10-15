from __future__ import annotations

from jarvis.config import SafetySettings
from jarvis.tools.base import ContextFlags, Prepared, Risk, ToolContext, ToolResult
from jarvis.tools.policy import EXFILTRATION_REASON, PolicyDecision, PolicyGate, app_risk
from jarvis.tools.registry import tool


@tool(risk=Risk.CONFIRM)
async def send(ctx: ToolContext) -> ToolResult:
    """Send something."""
    return ToolResult.success()


@tool(risk=Risk.SAFE)
async def look(ctx: ToolContext) -> ToolResult:
    """Look at something."""
    return ToolResult.success()


def test_config_cannot_lower_a_tool_floor() -> None:
    gate = PolicyGate(SafetySettings(tool_risk_overrides={"send": Risk.SAFE}))
    assert gate.evaluate(send, Prepared(args={}, summary="s")).risk is Risk.CONFIRM


def test_config_can_raise_risk_with_a_reason() -> None:
    gate = PolicyGate(SafetySettings(tool_risk_overrides={"look": Risk.BLOCKED}))
    decision = gate.evaluate(look, Prepared(args={}, summary="s"))
    assert decision.risk is Risk.BLOCKED
    assert decision.reason == "look is set to 'blocked' in config"


def test_preparer_can_raise_risk() -> None:
    gate = PolicyGate(SafetySettings())
    prepared = Prepared(args={}, summary="s", risk=Risk.CONFIRM, reason="why")
    decision = gate.evaluate(look, prepared)
    assert decision.risk is Risk.CONFIRM
    assert decision.reason == "why"


def test_app_risk_follows_allowlist() -> None:
    safety = SafetySettings(app_allowlist=["Notepad"])
    assert app_risk("notepad", safety) == (Risk.SAFE, None)
    risk, reason = app_risk("Spotify", safety)
    assert risk is Risk.CONFIRM
    assert reason == "Spotify is not in the app allowlist"
    blocking = SafetySettings(app_allowlist=[], unlisted_apps="block")
    assert app_risk("Spotify", blocking)[0] is Risk.BLOCKED


@tool(risk=Risk.SAFE, egress=True)
async def fetch(ctx: ToolContext) -> ToolResult:
    """Fetch something from the internet."""
    return ToolResult.success()


def test_egress_asks_only_when_private_and_outside_content_meet() -> None:
    gate = PolicyGate(SafetySettings())
    prepared = Prepared(args={}, summary="s")
    both = ContextFlags(private=True, untrusted=True)
    assert gate.evaluate(fetch, prepared, both).risk is Risk.CONFIRM
    assert gate.evaluate(fetch, prepared, both).reason == EXFILTRATION_REASON
    for flags in (ContextFlags(), ContextFlags(private=True), ContextFlags(untrusted=True)):
        assert gate.evaluate(fetch, prepared, flags).risk is Risk.SAFE
    assert gate.evaluate(look, prepared, both).risk is Risk.SAFE  # no egress, no rule
    blocked = Prepared(args={}, summary="s", risk=Risk.BLOCKED, reason="local address")
    assert gate.evaluate(fetch, blocked, both) == PolicyDecision(Risk.BLOCKED, "local address")
