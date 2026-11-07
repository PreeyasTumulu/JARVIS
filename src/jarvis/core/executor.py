"""Runs one tool call through validation, preparation, the policy gate, confirmation, and audit.

No tool runs without a clearance from the gate (see tools/base.py), so this is the only way in.
The agent graph runs the steps as separate nodes; `ToolExecutor.run` chains them for any other
caller.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import ValidationError

from jarvis.config import Settings
from jarvis.core.channel import ConfirmationRequest
from jarvis.core.events import (
    ConfirmationRequested,
    ConfirmationResolved,
    EventBus,
    ToolCallFinished,
    ToolCallStarted,
)
from jarvis.core.prompts import truncate, wrap_untrusted
from jarvis.llm.types import ToolCall
from jarvis.storage.repositories import AuditEntry, AuditLog
from jarvis.tools.base import (
    Clearance,
    ContextFlags,
    Prepared,
    Risk,
    Sensitivity,
    ToolContext,
    ToolError,
    ToolResult,
)
from jarvis.tools.policy import PolicyDecision, PolicyGate
from jarvis.tools.registry import Registry, Tool

log = logging.getLogger(__name__)

LIST_REPLY_HINT = (
    "(Reply in one or two spoken sentences: how many there are and at most three names. "
    "No list, no paths, no sizes, no dates.)"
)
TEXT_REPLY_HINT = (
    "(Reply in two or three short spoken sentences with the main point, unless the user asked "
    "for more. No lists.)"
)
SUMMARY_REPLY_HINT = (
    "(The summary is the answer: say it in one or two spoken sentences. Do not read out the "
    "data fields, codes, or units unless the user asked for them.)"
)
LONG_TEXT_CHARS = 400
LONG_LIST = 8  # items in a result's list (controls, links) that small models start reciting


class Decision(StrEnum):
    AUTO = "auto"  # safe, ran without asking
    CONFIRMED = "confirmed"  # user said yes
    DENIED = "denied"  # user said no
    TIMEOUT = "timeout"  # no answer in time, treated as no
    BLOCKED = "blocked"  # policy refused
    INVALID = "invalid"  # unknown tool or bad arguments, never reached the policy
    CANCELLED = "cancelled"  # the turn was stopped while this call was in progress
    DUPLICATE = "duplicate"  # the same call already ran this turn, so it was not run again


@dataclass(frozen=True)
class CallOutcome:
    call: ToolCall
    decision: Decision
    result: ToolResult
    duration_ms: int
    tool: Tool | None = None
    args: dict[str, Any] | None = None
    risk: Risk | None = None

    @property
    def sensitivity(self) -> Sensitivity:
        return self.tool.sensitivity if self.tool else Sensitivity.PUBLIC

    @property
    def flags(self) -> ContextFlags:
        """What this result adds to the model's context. Failures carry only Jarvis's own text."""
        if not self.result.ok or self.tool is None:
            return ContextFlags()
        return ContextFlags(
            private=self.tool.sensitivity is Sensitivity.PRIVATE, untrusted=self.tool.untrusted
        )

    def model_content(self, max_chars: int) -> str:
        """What the model sees for this call. Untrusted output is wrapped as data."""
        if self.result.ok:
            payload: dict[str, Any] = {"ok": True}
            if self.result.speech:
                payload["summary"] = self.result.speech  # a ready-made spoken answer
            payload["data"] = self.result.data
        else:
            payload = {"ok": False, "error": self.result.error}
        text = truncate(json.dumps(payload, ensure_ascii=False, default=str), max_chars)
        if self.tool is not None and self.tool.untrusted and self.result.ok:
            text = wrap_untrusted(self.call.name, text)
        data = self.result.data if self.result.ok else None
        if self.result.ok and self.result.hint:
            text += f"\n{self.result.hint}"
        if isinstance(data, list) and len(data) > 1:
            # Small models mirror list data as long markdown lists; the reply is spoken.
            text += f"\n{LIST_REPLY_HINT}"
        elif isinstance(data, dict) and (
            len(str(data.get("text") or "")) > LONG_TEXT_CHARS
            or any(isinstance(v, list) and len(v) > LONG_LIST for v in data.values())
        ):
            # A page or file read in full otherwise comes back as a minute-long summary, and
            # a window's controls were recited one by one (35 seconds for "what does it say").
            text += f"\n{TEXT_REPLY_HINT}"
        elif isinstance(data, dict) and self.result.speech and not self.result.hint:
            # Weather came back as a recital of every field (humidity, wind, "weather code 3")
            # that took 14 seconds to generate; the summary already says what matters.
            text += f"\n{SUMMARY_REPLY_HINT}"
        return text

    def summary(self) -> str:
        if not self.result.ok:
            return self.result.error or "failed"
        if self.result.speech:
            return self.result.speech
        return truncate(json.dumps(self.result.data, ensure_ascii=False, default=str), 160)


@dataclass(frozen=True)
class Checked:
    """A call whose tool exists and whose arguments fit its schema."""

    call: ToolCall
    tool: Tool
    args: dict[str, Any]
    started: float


@dataclass(frozen=True)
class Gated:
    """A call the policy gate has rated. It runs only through `ToolExecutor.execute`."""

    call: ToolCall
    tool: Tool
    prepared: Prepared
    verdict: PolicyDecision
    started: float

    @property
    def needs_confirmation(self) -> bool:
        return self.verdict.risk is Risk.CONFIRM


class ToolExecutor:
    def __init__(
        self,
        *,
        settings: Settings,
        registry: Registry,
        policy: PolicyGate,
        audit: AuditLog,
        bus: EventBus,
    ) -> None:
        self._settings = settings
        self._registry = registry
        self._policy = policy
        self._audit = audit
        self._bus = bus
        self._detached: set[asyncio.Future[ToolResult]] = set()  # left running after a stop

    def tool_names(self) -> list[str]:
        return self._registry.names()

    async def run(self, call: ToolCall, ctx: ToolContext) -> CallOutcome:
        """Every step for one call, for callers outside the agent graph."""
        started = time.perf_counter()
        try:
            outcome = await self._run(call, ctx, started)
        except asyncio.CancelledError:
            self.record_cancelled(call, started, ctx)
            raise
        await self.finish(outcome, ctx)
        return outcome

    async def _run(self, call: ToolCall, ctx: ToolContext, started: float) -> CallOutcome:
        checked = self.check(call, started)
        if isinstance(checked, CallOutcome):
            return checked
        gated = await self.gate(checked, ctx)
        if isinstance(gated, CallOutcome):
            return gated
        confirmed = False
        if gated.needs_confirmation:
            decision = await self.confirm(gated, ctx)
            if decision is not Decision.CONFIRMED:
                return self.refusal(gated, decision)
            confirmed = True
        return await self.execute(gated, ctx, confirmed=confirmed)

    # The steps

    def check(self, call: ToolCall, started: float | None = None) -> Checked | CallOutcome:
        """The tool exists and the arguments are a JSON object that fits its schema."""
        started = time.perf_counter() if started is None else started
        tool = self._registry.get(call.name)

        def invalid(message: str, args: dict[str, Any] | None = None) -> CallOutcome:
            return CallOutcome(
                call=call,
                decision=Decision.INVALID,
                result=ToolResult.failure(message),
                duration_ms=_elapsed_ms(started),
                tool=tool,
                args=args,
            )

        if tool is None:
            available = ", ".join(self._registry.names())
            return invalid(f"Unknown tool '{call.name}'. Available tools: {available}.")
        try:
            raw = json.loads(call.arguments or "{}")
        except json.JSONDecodeError:
            return invalid("The arguments were not valid JSON.")
        if not isinstance(raw, dict):
            return invalid("The arguments must be a JSON object.")
        try:
            args = tool.validate(raw)
        except ValidationError as exc:
            problems = "; ".join(
                f"{'.'.join(str(p) for p in err['loc']) or 'arguments'}: {err['msg']}"
                for err in exc.errors()
            )
            return invalid(f"Invalid arguments for {tool.name}: {problems}", raw)
        return Checked(call, tool, args, started)

    async def gate(self, checked: Checked, ctx: ToolContext) -> Gated | CallOutcome:
        """Resolve the arguments (no side effects) and let the policy rate the call."""
        call, tool, started = checked.call, checked.tool, checked.started
        try:
            prepared = await tool.prepare(ctx, checked.args)
        except ToolError as exc:
            return CallOutcome(
                call=call,
                decision=Decision.AUTO,
                result=ToolResult.failure(str(exc)),
                duration_ms=_elapsed_ms(started),
                tool=tool,
                args=checked.args,
            )
        verdict = self._policy.evaluate(tool, prepared, ctx.flags)
        await self._bus.publish(
            ToolCallStarted(
                turn_id=ctx.turn_id,
                call_id=call.id,
                tool=tool.name,
                args=prepared.args,
                risk=verdict.risk,
            )
        )
        gated = Gated(call, tool, prepared, verdict, started)
        if verdict.risk is Risk.BLOCKED:
            reason = verdict.reason or "this action is not allowed"
            return self._outcome(gated, Decision.BLOCKED, ToolResult.failure(f"Blocked: {reason}."))
        return gated

    async def confirm(self, gated: Gated, ctx: ToolContext) -> Decision:
        """Ask on the channel that started the turn. No answer in time counts as no."""
        request = ConfirmationRequest(
            request_id=uuid.uuid4().hex[:12],
            tool=gated.tool.name,
            summary=gated.prepared.summary,
            digest=gated.prepared.digest,
            reason=gated.verdict.reason,
            timeout_s=self._settings.safety.confirm_timeout_s,
        )
        await self._bus.publish(ConfirmationRequested(turn_id=ctx.turn_id, request=request))
        decision = Decision.CANCELLED
        try:
            async with asyncio.timeout(request.timeout_s):
                approved = await ctx.channel.confirm(request)
            decision = Decision.CONFIRMED if approved is True else Decision.DENIED
        except TimeoutError:
            decision = Decision.TIMEOUT
        finally:
            # Every channel needs to know the question is closed.
            answered = decision in (Decision.CONFIRMED, Decision.DENIED)
            await self._bus.publish(
                ConfirmationResolved(
                    turn_id=ctx.turn_id,
                    request_id=request.request_id,
                    decision=decision,
                    via=ctx.channel.name if answered else None,
                )
            )
        return decision

    def refusal(self, gated: Gated, decision: Decision) -> CallOutcome:
        """The outcome of a no, or of no answer in time."""
        summary = gated.prepared.summary
        if decision is Decision.DENIED:
            message = (
                f"The person talking to you said no to '{summary}', so it was not done. "
                "Do not retry, and reply with exactly: Okay, I won't."
            )
        else:
            message = (
                f"No confirmation was given in time for '{summary}', so it was not done. "
                "Tell the user briefly."
            )
        return self._outcome(gated, decision, ToolResult.failure(message))

    async def execute(self, gated: Gated, ctx: ToolContext, *, confirmed: bool) -> CallOutcome:
        """Run the call with a clearance from the gate, within the tool's time limit."""
        clearance = self._policy.clear(gated.tool, gated.prepared, ctx.flags, confirmed=confirmed)
        decision = Decision.CONFIRMED if clearance.decision == "confirmed" else Decision.AUTO
        task = asyncio.ensure_future(self._invoke(gated, ctx, clearance))
        if gated.tool.cancel_on_interruption:
            result = await task
        else:
            try:
                result = await asyncio.shield(task)
            except asyncio.CancelledError:
                self._detach(task, gated, decision, ctx)
                raise
        return self._outcome(gated, decision, result)

    async def finish(self, outcome: CallOutcome, ctx: ToolContext) -> None:
        """Audit the call and tell every channel how it ended."""
        self._record(outcome, ctx)
        await self._bus.publish(
            ToolCallFinished(
                turn_id=ctx.turn_id,
                call_id=outcome.call.id,
                tool=outcome.call.name,
                decision=outcome.decision,
                ok=outcome.result.ok,
                summary=outcome.summary(),
                duration_ms=outcome.duration_ms,
            )
        )

    def record_cancelled(self, call: ToolCall, started: float, ctx: ToolContext) -> CallOutcome:
        """Audit a call that was in progress when the turn was stopped."""
        outcome = CallOutcome(
            call=call,
            decision=Decision.CANCELLED,
            result=ToolResult.failure("Stopped by the user."),
            duration_ms=_elapsed_ms(started),
            tool=self._registry.get(call.name),
        )
        self._record(outcome, ctx)
        return outcome

    async def drain(self) -> None:
        """Wait for calls left running after a stop (at shutdown, and in tests)."""
        while self._detached:
            await asyncio.gather(*list(self._detached), return_exceptions=True)
            await asyncio.sleep(0)

    # Helpers

    def _outcome(self, gated: Gated, decision: Decision, result: ToolResult) -> CallOutcome:
        return CallOutcome(
            call=gated.call,
            decision=decision,
            result=result,
            duration_ms=_elapsed_ms(gated.started),
            tool=gated.tool,
            args=gated.prepared.args,
            risk=gated.verdict.risk,
        )

    async def _invoke(self, gated: Gated, ctx: ToolContext, clearance: Clearance) -> ToolResult:
        tool = gated.tool
        timeout = tool.timeout_s or self._settings.agent.tool_timeout_s
        try:
            async with asyncio.timeout(timeout):
                return await tool(ctx, clearance, **gated.prepared.args)
        except TimeoutError:
            return ToolResult.failure(f"{tool.name} timed out after {timeout:.0f} seconds.")
        except ToolError as exc:
            return ToolResult.failure(str(exc))
        except Exception as exc:
            log.exception("Tool %s crashed", tool.name)
            return ToolResult.failure(f"{tool.name} failed unexpectedly ({type(exc).__name__}).")

    def _detach(
        self, task: asyncio.Future[ToolResult], gated: Gated, decision: Decision, ctx: ToolContext
    ) -> None:
        """The turn was stopped, but this tool finishes its work; audit it when it does."""
        log.info("Turn stopped; %s keeps running until it finishes", gated.tool.name)
        self._detached.add(task)

        def done(finished: asyncio.Future[ToolResult]) -> None:
            self._detached.discard(finished)
            if finished.cancelled():
                result = ToolResult.failure("Stopped by the user.")
            elif (error := finished.exception()) is not None:
                result = ToolResult.failure(f"{gated.tool.name} failed ({type(error).__name__}).")
            else:
                result = finished.result()
            self._record(self._outcome(gated, decision, result), ctx)

        task.add_done_callback(done)

    def _record(self, outcome: CallOutcome, ctx: ToolContext) -> None:
        confirmed_via = ctx.channel.name if outcome.decision is Decision.CONFIRMED else None
        try:
            self._audit.record(
                AuditEntry(
                    session_id=ctx.session_id,
                    turn_id=ctx.turn_id,
                    call_id=outcome.call.id,
                    tool=outcome.call.name,
                    args=outcome.args,
                    risk=outcome.risk,
                    decision=outcome.decision,
                    confirmed_via=confirmed_via,
                    ok=outcome.result.ok,
                    result=outcome.result.data if outcome.result.ok else None,
                    error=outcome.result.error,
                    duration_ms=outcome.duration_ms,
                    handled_by=ctx.handled_by,
                )
            )
        except Exception:
            log.exception("Failed to write audit entry for %s", outcome.call.name)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
