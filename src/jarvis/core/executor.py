"""Runs one tool call through validation, preparation, the policy gate, confirmation, and audit."""

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
    ContextFlags,
    Prepared,
    Risk,
    Sensitivity,
    ToolContext,
    ToolError,
    ToolResult,
)
from jarvis.tools.policy import PolicyGate
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


class Decision(StrEnum):
    AUTO = "auto"  # safe, ran without asking
    CONFIRMED = "confirmed"  # user said yes
    DENIED = "denied"  # user said no
    TIMEOUT = "timeout"  # no answer in time, treated as no
    BLOCKED = "blocked"  # policy refused
    INVALID = "invalid"  # unknown tool or bad arguments, never reached the policy
    CANCELLED = "cancelled"  # the turn was stopped while this call was in progress


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
        elif isinstance(data, dict) and len(str(data.get("text") or "")) > LONG_TEXT_CHARS:
            # A page or file read in full otherwise comes back as a minute-long summary.
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

    async def run(self, call: ToolCall, ctx: ToolContext) -> CallOutcome:
        started = time.perf_counter()
        tool = self._registry.get(call.name)
        try:
            outcome = await self._run(call, ctx, tool, started)
        except asyncio.CancelledError:
            outcome = CallOutcome(
                call=call,
                decision=Decision.CANCELLED,
                result=ToolResult.failure("Stopped by the user."),
                duration_ms=_elapsed_ms(started),
                tool=tool,
            )
            self._record(outcome, ctx)
            raise
        self._record(outcome, ctx)
        await self._bus.publish(
            ToolCallFinished(
                turn_id=ctx.turn_id,
                call_id=call.id,
                tool=call.name,
                decision=outcome.decision,
                ok=outcome.result.ok,
                summary=outcome.summary(),
                duration_ms=outcome.duration_ms,
            )
        )
        return outcome

    async def _run(
        self, call: ToolCall, ctx: ToolContext, tool: Tool | None, started: float
    ) -> CallOutcome:
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

        try:
            prepared = await tool.prepare(ctx, args)
        except ToolError as exc:
            return CallOutcome(
                call=call,
                decision=Decision.AUTO,
                result=ToolResult.failure(str(exc)),
                duration_ms=_elapsed_ms(started),
                tool=tool,
                args=args,
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

        def finish(decision: Decision, result: ToolResult) -> CallOutcome:
            return CallOutcome(
                call=call,
                decision=decision,
                result=result,
                duration_ms=_elapsed_ms(started),
                tool=tool,
                args=prepared.args,
                risk=verdict.risk,
            )

        if verdict.risk is Risk.BLOCKED:
            reason = verdict.reason or "this action is not allowed"
            return finish(Decision.BLOCKED, ToolResult.failure(f"Blocked: {reason}."))

        decision = Decision.AUTO
        if verdict.risk is Risk.CONFIRM:
            decision = await self._confirm(tool, prepared, verdict.reason, ctx)
            if decision is Decision.DENIED:
                return finish(
                    decision,
                    ToolResult.failure(
                        f"The user said no to '{prepared.summary}', so it was not done. "
                        "Acknowledge that briefly and do not retry."
                    ),
                )
            if decision is Decision.TIMEOUT:
                return finish(
                    decision,
                    ToolResult.failure(
                        f"No confirmation was given in time for '{prepared.summary}', so it "
                        "was not done. Tell the user briefly."
                    ),
                )

        return finish(decision, await self._execute(tool, prepared, ctx))

    async def _confirm(
        self, tool: Tool, prepared: Prepared, reason: str | None, ctx: ToolContext
    ) -> Decision:
        request = ConfirmationRequest(
            request_id=uuid.uuid4().hex[:12],
            tool=tool.name,
            summary=prepared.summary,
            digest=prepared.digest,
            reason=reason,
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
            # Every channel (the web UI especially) needs to know the question is closed.
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

    async def _execute(self, tool: Tool, prepared: Prepared, ctx: ToolContext) -> ToolResult:
        timeout = tool.timeout_s or self._settings.agent.tool_timeout_s
        try:
            async with asyncio.timeout(timeout):
                return await tool(ctx, **prepared.args)
        except TimeoutError:
            return ToolResult.failure(f"{tool.name} timed out after {timeout:.0f} seconds.")
        except ToolError as exc:
            return ToolResult.failure(str(exc))
        except Exception as exc:
            log.exception("Tool %s crashed", tool.name)
            return ToolResult.failure(f"{tool.name} failed unexpectedly ({type(exc).__name__}).")

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
                )
            )
        except Exception:
            log.exception("Failed to write audit entry for %s", outcome.call.name)


def _elapsed_ms(started: float) -> int:
    return int((time.perf_counter() - started) * 1000)
