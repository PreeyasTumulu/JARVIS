"""The guard: what a proposed tool call must pass before the policy gate sees it.

Taken from Leon's runtime argument guards (docs/RESEARCH.md 6.2). Small local models write
calls with a near-miss tool name or JSON with single quotes; the guard repairs those once, in
code, instead of spending a model call. It also never runs the same call twice in one turn (a
model looping on a result, or asking you twice for something you refused), and caps the tool
calls in a turn. Safety does not depend on it: the gate still rates every call it lets through.
"""

from __future__ import annotations

import ast
import json
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass, field, replace

from rapidfuzz import fuzz, process

from jarvis.core.executor import CallOutcome, Checked, Decision, ToolExecutor
from jarvis.llm.types import ToolCall
from jarvis.tools.base import ToolResult, args_digest

log = logging.getLogger(__name__)

NAME_MATCH = 88  # rapidfuzz WRatio: "open_ap" and "openapp" pass, "open_file" for open_app fails
_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$")
# Calls that ran (or were answered) are not repeated: a refusal must not be asked again.
_SETTLED = {
    Decision.AUTO,
    Decision.CONFIRMED,
    Decision.DENIED,
    Decision.TIMEOUT,
    Decision.BLOCKED,
}
DUPLICATE_NOTE = (
    "This exact call already ran in this request, so it was not run again. Its result is "
    "above. Answer from it."
)
CAP_NOTE = (
    "Too many tool calls for one request, so this one was not run. Answer with what you have."
)


@dataclass
class Screened:
    """The guard's verdict on one model step."""

    passed: list[Checked] = field(default_factory=list)
    rejected: list[CallOutcome] = field(default_factory=list)  # invalid, duplicate, or over the cap
    capped: bool = False


@dataclass
class Guard:
    executor: ToolExecutor
    max_calls: int
    offered: list[str] = field(default_factory=list)  # the tool names this turn's model saw
    _settled: dict[tuple[str, str], CallOutcome] = field(default_factory=dict)
    _ran: int = 0

    def screen(self, calls: Iterable[ToolCall]) -> Screened:
        screened = Screened()
        this_step: set[tuple[str, str]] = set()
        for call in calls:
            checked = self._check(call)
            if isinstance(checked, CallOutcome):
                screened.rejected.append(checked)
                continue
            key = (checked.tool.name, args_digest(checked.args))
            earlier = self._settled.get(key)
            if earlier is not None or key in this_step:
                screened.rejected.append(self._duplicate(checked, earlier))
                continue
            if self._ran >= self.max_calls:
                screened.capped = True
                screened.rejected.append(self._note(checked, CAP_NOTE, Decision.INVALID))
                continue
            this_step.add(key)
            self._ran += 1
            screened.passed.append(checked)
        return screened

    def settled(self, checked: Checked, outcome: CallOutcome) -> None:
        """Remember a call's outcome, so the same call is not run again this turn."""
        if outcome.decision in _SETTLED:
            self._settled[(checked.tool.name, args_digest(checked.args))] = outcome

    def _check(self, call: ToolCall) -> Checked | CallOutcome:
        checked = self.executor.check(call)
        if not isinstance(checked, CallOutcome):
            return checked
        repaired = self._repair(call, checked)
        if repaired is None:
            return checked
        again = self.executor.check(repaired)
        if isinstance(again, CallOutcome):
            return checked  # the model sees the original problem, which it can fix
        log.info(
            "Guard repaired a call to %s (was %s %s)", repaired.name, call.name, call.arguments
        )
        return again

    def _repair(self, call: ToolCall, failed: CallOutcome) -> ToolCall | None:
        name, arguments = call.name, call.arguments
        if failed.tool is None:
            known = self.offered or self.executor_names()
            best = process.extractOne(name, known, scorer=fuzz.WRatio)
            if best is None or best[1] < NAME_MATCH:
                return None
            name = best[0]
        fixed = repair_json(arguments)
        if fixed is not None:
            arguments = fixed
        if (name, arguments) == (call.name, call.arguments):
            return None
        return replace(call, name=name, arguments=arguments)

    def executor_names(self) -> list[str]:
        return self.executor.tool_names()

    def _duplicate(self, checked: Checked, earlier: CallOutcome | None) -> CallOutcome:
        if earlier is None:
            return self._note(checked, DUPLICATE_NOTE, Decision.DUPLICATE)
        # The earlier result, so the model can answer; a refusal stays a refusal.
        error = earlier.result.error or "failed"
        result = earlier.result if earlier.result.ok else ToolResult.failure(error)
        return CallOutcome(
            call=checked.call,
            decision=Decision.DUPLICATE,
            result=result.model_copy(update={"hint": DUPLICATE_NOTE}),
            duration_ms=0,
            tool=checked.tool,
            args=checked.args,
            risk=earlier.risk,
        )

    def _note(self, checked: Checked, note: str, decision: Decision) -> CallOutcome:
        return CallOutcome(
            call=checked.call,
            decision=decision,
            result=ToolResult.failure(note),
            duration_ms=0,
            tool=checked.tool,
            args=checked.args,
        )


def repair_json(text: str) -> str | None:
    """Arguments a small model meant as JSON: fenced, single-quoted, Python's True and None,
    or with a trailing comma. Returns compact JSON, or None if it was fine or hopeless."""
    raw = (text or "").strip() or "{}"
    try:
        json.loads(raw)
        return None
    except json.JSONDecodeError:
        pass
    candidate = _FENCE.sub("", raw).strip()
    start, end = candidate.find("{"), candidate.rfind("}")
    if start != -1 and end > start:
        candidate = candidate[start : end + 1]
    candidate = re.sub(r",\s*([}\]])", r"\1", candidate)
    for attempt in (candidate, _pythonish(candidate)):
        try:
            value = json.loads(attempt)
        except (json.JSONDecodeError, TypeError):
            try:
                value = ast.literal_eval(attempt)
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                continue
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
    return None


_PYTHON_WORDS = {"true": "True", "false": "False", "null": "None"}


def _pythonish(text: str) -> str:
    return re.sub(r"\b(true|false|null)\b", lambda m: _PYTHON_WORDS[m[1]], text)
