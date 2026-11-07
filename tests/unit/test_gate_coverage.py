"""Every way to run a tool meets the policy gate (ADR-083). Checked in the code, not trusted.

The graph has no edge to "execute" that skips "gate", a tool will not run without a one-time
clearance for exactly its arguments, and only the policy gate can issue one. The source scans
below keep it that way as new code arrives: a new module that calls a tool function directly,
issues a clearance, or passes one to a tool fails here.
"""

from __future__ import annotations

import ast
import dataclasses
from pathlib import Path

import pytest

from jarvis.tools.base import Clearance, Prepared, Risk, ToolContext, ToolResult, args_digest
from jarvis.tools.policy import PolicyGate
from jarvis.tools.registry import Registry, tool
from tests.conftest import REPO, MakeApp

SRC = REPO / "src" / "jarvis"


def _calls(predicate: object) -> dict[str, list[int]]:
    """Source files (relative to src/jarvis) and lines where a call matches the predicate."""
    found: dict[str, list[int]] = {}
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and predicate(node):  # type: ignore[operator]
                found.setdefault(path.relative_to(SRC).as_posix(), []).append(node.lineno)
    return found


def _name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def test_tool_functions_are_called_only_by_the_tool_itself() -> None:
    direct = _calls(lambda call: _name(call.func) == "fn" and isinstance(call.func, ast.Attribute))
    assert set(direct) == {"tools/registry.py"}


def test_only_the_policy_gate_issues_clearances() -> None:
    issued = _calls(lambda call: _name(call.func) == "issue_clearance")
    assert set(issued) == {"tools/policy.py"}
    made = _calls(lambda call: _name(call.func) == "Clearance")
    assert set(made) == {"tools/base.py"}  # inside issue_clearance


def test_only_the_executor_runs_tools() -> None:
    def passes_a_clearance(call: ast.Call) -> bool:
        return any(_name(arg) == "clearance" for arg in call.args[1:2])

    assert set(_calls(passes_a_clearance)) == {"core/executor.py"}


def test_only_the_executor_asks_the_gate_for_a_clearance() -> None:
    cleared = _calls(
        lambda call: (
            isinstance(call.func, ast.Attribute)
            and call.func.attr == "clear"
            and _name(call.func.value) == "_policy"
        )
    )
    assert set(cleared) == {"core/executor.py"}


def test_every_path_to_execute_passes_the_gate(make_app: MakeApp) -> None:
    graph = make_app().app.agent._graph.compiled().get_graph()
    into_execute = {edge.source for edge in graph.edges if edge.target == "execute"}
    assert into_execute == {"gate", "await_confirmation"}
    into_confirmation = {e.source for e in graph.edges if e.target == "await_confirmation"}
    assert into_confirmation == {"gate"}


# The tool and its clearance


@tool(risk=Risk.SAFE)
async def echo(ctx: ToolContext, text: str) -> ToolResult:
    """Say the text back.

    Args:
        text: What to say.
    """
    return ToolResult.success(speech=text)


@tool(risk=Risk.CONFIRM)
async def wipe(ctx: ToolContext) -> ToolResult:
    """Wipe something."""
    return ToolResult.success(speech="wiped")


def _prepared(args: dict[str, str], risk: Risk = Risk.SAFE) -> Prepared:
    return Prepared(args=args, summary="test", risk=risk)


async def test_a_tool_will_not_run_without_a_clearance(make_app: MakeApp) -> None:
    ctx = ToolContext(make_app().app.settings, None, None, "s", "t")  # type: ignore[arg-type]
    gate = PolicyGate(make_app().app.settings.safety)
    forged = Clearance("echo", args_digest({"text": "hi"}), Risk.SAFE, "auto", object())
    with pytest.raises(PermissionError, match="not cleared"):
        await echo(ctx, forged, text="hi")

    clearance = gate.clear(echo, _prepared({"text": "hi"}), None, confirmed=False)
    with pytest.raises(PermissionError, match="does not cover"):
        await echo(ctx, clearance, text="something else")  # bound to the approved arguments
    assert (await echo(ctx, clearance, text="hi")).speech == "hi"
    with pytest.raises(PermissionError, match="already used"):
        await echo(ctx, clearance, text="hi")  # one use only


def test_the_gate_decides_again_when_asked_for_a_clearance(make_app: MakeApp) -> None:
    gate = PolicyGate(make_app().app.settings.safety)
    with pytest.raises(PermissionError, match="confirmation"):
        gate.clear(wipe, _prepared({}, Risk.CONFIRM), None, confirmed=False)
    assert gate.clear(wipe, _prepared({}, Risk.CONFIRM), None, confirmed=True).decision == (
        "confirmed"
    )
    # A prepare step cannot lower a tool's own risk floor.
    with pytest.raises(PermissionError):
        gate.clear(wipe, _prepared({}, Risk.SAFE), None, confirmed=False)


def test_tools_cannot_be_changed_after_they_are_made() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        echo.risk = Risk.SAFE  # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        wipe.fn = echo.fn  # type: ignore[misc]


def test_the_registry_refuses_a_second_tool_with_the_same_name() -> None:
    registry = Registry()
    registry.register(echo)
    with pytest.raises(ValueError, match="already registered"):
        registry.register(echo)


def test_the_source_scan_reads_every_module() -> None:
    files = list(SRC.rglob("*.py"))
    assert len(files) > 100
    assert Path(SRC / "core" / "executor.py") in files
