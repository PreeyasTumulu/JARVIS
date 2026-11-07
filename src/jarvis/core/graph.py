"""The agent loop as a LangGraph graph (ADR-079, ADR-083).

Every request walks the same nodes:

- route: the router pipeline (core/pipeline.py) may hand over a tool call without a model.
- think: the model (local, or a cloud model for heavy public questions) answers or calls tools.
- guard: repairs a near-miss call once, drops repeats, caps the calls in a turn (core/guard.py).
- gate: the policy gate rates the call: safe, confirm, or blocked.
- await_confirmation: asks you, and waits for yes, no, or the time limit.
- execute: runs the tool with the gate's one-time clearance.
- respond: the answer for this turn.

The gate and the confirmation are nodes every call passes through; there is no edge around
them, and a tool refuses to run without the gate's clearance anyway (tools/base.py). Nothing
about safety lives in a prompt. LangGraph is imported only when the first graph is built,
because it takes about 2.5 s to import on this laptop.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, TypedDict

from jarvis.core.events import AgentStateChanged, ModelReplied
from jarvis.core.executor import CallOutcome, Checked, Decision, Gated
from jarvis.core.guard import Guard
from jarvis.core.pipeline import AGENT, CLOUD, FAST_STAGES, RouteRequest, route
from jarvis.core.prompts import system_prompt
from jarvis.core.speech import SpeechStream
from jarvis.llm.router import CLOUD_TOOLS, PrivacyViolation
from jarvis.llm.types import LLMError, LLMReply, ToolCall
from jarvis.tools.base import ContextFlags, ToolContext

if TYPE_CHECKING:
    from jarvis.core.agent import Agent
    from jarvis.llm.router import CloudModel

log = logging.getLogger(__name__)

# Traces go to LangSmith's cloud when these are set, and a turn holds private data. Jarvis
# switches them off for its own process whatever the environment says (CLAUDE.md: nothing
# private reaches a cloud service).
for _variable in (
    "LANGSMITH_TRACING",
    "LANGSMITH_TRACING_V2",
    "LANGCHAIN_TRACING_V2",
    "LANGCHAIN_TRACING",
):
    os.environ[_variable] = "false"

NODES = ("route", "think", "guard", "gate", "await_confirmation", "execute", "respond")
NODE_STATES = {
    "route": "thinking",
    "think": "thinking",
    "guard": "thinking",
    "gate": "thinking",
    "await_confirmation": "awaiting_confirmation",
    "execute": "running_tool",
    "respond": "responding",
}
RECURSION_LIMIT = 200  # LangGraph's own step limit; the guard and max_iterations stop far sooner
DONE = "Done."
NOT_UNDERSTOOD = "Sorry, I didn't get that. Could you say it another way?"
EMPTY_REPLY_NUDGE = (
    "(Your last reply was empty. Call the right tool, or answer in one short sentence.)"
)
GAVE_UP = "I couldn't work out how to do that. Could you say it another way?"
_FAST_REFUSALS = {
    Decision.DENIED: "Okay, I won't.",
    Decision.TIMEOUT: "No answer, so I didn't do it.",
}


class TurnState(TypedDict, total=False):
    """What LangGraph checkpoints: plain values only. Live objects stay in `TurnRuntime`."""

    handled_by: str  # the router stage, or "cloud" (ADR-083)
    step: int  # model calls so far
    queue: list[str]  # ids of calls past the guard, waiting for the gate
    current: str  # the call at the gate or waiting for an answer
    verdict: str  # the gate's word on it: confirm, run, or done
    go: str  # where route, think, and guard send the turn next
    reply: str
    status: str


@dataclass
class CloudTurn:
    """A heavy public question tried on cloud models first (ADR-045): fresh context only."""

    models: list[CloudModel]
    prompt: list[dict[str, Any]]
    schemas: list[dict[str, Any]]
    index: int = 0
    steps: int = 0
    messages: list[dict[str, Any]] = field(default_factory=list)
    flags: ContextFlags = field(default_factory=ContextFlags)

    def __post_init__(self) -> None:
        self.messages = list(self.prompt)

    @property
    def model(self) -> CloudModel | None:
        return self.models[self.index] if self.index < len(self.models) else None

    def next_provider(self) -> None:
        self.index += 1
        self.steps = 0
        self.messages = list(self.prompt)
        self.flags = ContextFlags()


@dataclass
class TurnRuntime:
    """One turn's live objects, handed to every node as LangGraph's runtime context."""

    turn_id: str
    text: str
    ctx: ToolContext
    guard: Guard
    started: float
    times: dict[str, int]
    speech: SpeechStream | None = None
    offer_pending: bool = False
    model: str = ""
    outcomes: list[CallOutcome] = field(default_factory=list)
    proposed: list[ToolCall] = field(default_factory=list)
    checked: dict[str, Checked] = field(default_factory=dict)
    gated: dict[str, Gated] = field(default_factory=dict)
    confirmed: set[str] = field(default_factory=set)
    schemas: list[dict[str, Any]] | None = None
    cloud: CloudTurn | None = None
    last: CallOutcome | None = None
    invalid_rounds: int = 0

    def since_start_ms(self) -> int:
        return int((time.perf_counter() - self.started) * 1000)

    def add_time(self, key: str, ms: int) -> None:
        self.times[key] = self.times.get(key, 0) + ms


class AgentGraph:
    """Builds the graph once per agent and runs one turn through it."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent
        self._compiled: Any = None
        self._saver: Any = None
        self._build_lock = threading.Lock()  # the warm-up thread and a first turn may race

    def compiled(self) -> Any:
        with self._build_lock:
            return self._build()

    def _build(self) -> Any:
        if self._compiled is None:
            from langgraph.checkpoint.memory import InMemorySaver
            from langgraph.graph import END, START, StateGraph

            builder: Any = StateGraph(TurnState, context_schema=TurnRuntime)
            for name in NODES:
                builder.add_node(name, getattr(self, name))
            builder.add_edge(START, "route")
            builder.add_conditional_edges("route", _go, ["guard", "think"])
            builder.add_conditional_edges("think", _go, ["guard", "respond"])
            builder.add_conditional_edges("guard", _go, ["gate", "think", "respond"])
            builder.add_conditional_edges(
                "gate", _after_gate, ["await_confirmation", "execute", "gate", "think", "respond"]
            )
            builder.add_conditional_edges(
                "await_confirmation", _after_answer, ["execute", "gate", "think", "respond"]
            )
            builder.add_conditional_edges("execute", _after_call, ["gate", "think", "respond"])
            builder.add_edge("respond", END)
            # In memory, one thread per turn, deleted when the turn ends (ADR-083): it says
            # where a stopped turn was, and nothing private outlives the turn in it.
            self._saver = InMemorySaver()
            self._compiled = builder.compile(checkpointer=self._saver)
        return self._compiled

    def mermaid(self) -> str:
        """The graph as a Mermaid diagram (docs/ARCHITECTURE.md is generated from this)."""
        return str(self.compiled().get_graph().draw_mermaid())

    async def run(self, rt: TurnRuntime) -> TurnState:
        graph = self.compiled()
        config: dict[str, Any] = {
            "configurable": {"thread_id": rt.turn_id},
            "recursion_limit": RECURSION_LIMIT,
        }
        try:
            state: TurnState = await graph.ainvoke(
                {"handled_by": AGENT, "step": 0, "queue": []}, config, context=rt
            )
            return state
        except BaseException:
            try:
                snapshot = await graph.aget_state(config)
                log.info("Turn %s ended early in %s", rt.turn_id, ", ".join(snapshot.next) or "-")
            except Exception:
                pass
            raise
        finally:
            self._saver.delete_thread(rt.turn_id)

    # Nodes

    async def route(self, state: TurnState, runtime: Any) -> TurnState:
        rt: TurnRuntime = runtime.context
        agent = self._agent
        await self._enter(rt, "route")
        settings = agent.settings.router
        request = RouteRequest(rt.text, agent.registry, agent.services, rt.offer_pending)
        routed, times = await route(request, settings.pipeline, settings.stage_timeout_ms)
        rt.times["route_ms"] = sum(times.values())
        if routed is not None:
            call = ToolCall(id=f"fast_{rt.turn_id}", name=routed.name, arguments=routed.arguments)
            rt.proposed = [call]
            rt.ctx.handled_by = routed.stage
            agent.conversation.append(
                {"role": "assistant", "content": "", "tool_calls": [call.as_message_part()]}
            )
            return {"handled_by": routed.stage, "go": "guard"}
        router = agent.router
        if router is not None and router.wants_cloud(rt.text):
            models = list(router.available())
            if models:
                tools = [t for n in CLOUD_TOOLS if (t := agent.registry.get(n)) is not None]
                prompt = [
                    {"role": "system", "content": system_prompt(agent.now())},
                    {"role": "user", "content": rt.text},
                ]
                rt.cloud = CloudTurn(models, prompt, [t.schema() for t in tools])
        return {"handled_by": AGENT, "go": "think"}

    async def think(self, state: TurnState, runtime: Any) -> TurnState:
        rt: TurnRuntime = runtime.context
        agent = self._agent
        await self._enter(rt, "think")
        if rt.cloud is not None:
            update = await self._think_cloud(rt)
            if update is not None:
                return update
            rt.cloud = None  # the local model takes the whole turn
            rt.ctx.handled_by = AGENT
        limits = agent.settings.agent
        step = state.get("step", 0) + 1
        if step > limits.max_iterations:
            text = f"I couldn't finish that within {limits.max_iterations} steps, so I stopped."
            agent.conversation.append({"role": "assistant", "content": text})
            return {"reply": text, "status": "limit", "go": "respond"}
        if rt.schemas is None:
            rt.schemas = await agent.tool_schemas()
            rt.guard.offered = [s["function"]["name"] for s in rt.schemas]
        reply = await self._complete(agent.model_messages(), rt.schemas, rt)
        if not reply.tool_calls and not reply.text.strip():
            # Hermes sometimes answers with nothing at all (Ollama drops a tool call it could
            # not parse). One nudge recovers it; the nudge never enters the history.
            log.info("Empty model reply in turn %s; asking once more", rt.turn_id)
            nudge = {"role": "user", "content": EMPTY_REPLY_NUDGE}
            reply = await self._complete([*agent.model_messages(), nudge], rt.schemas, rt)
        rt.model = reply.model
        calls = reply.tool_calls[: limits.max_tool_calls_per_step]
        await self._replied(rt, reply, len(calls))
        if not calls:
            text = reply.text.strip() or (DONE if rt.outcomes else NOT_UNDERSTOOD)
            agent.conversation.append({"role": "assistant", "content": text})
            return {"reply": text, "status": "ok", "step": step, "go": "respond"}
        if rt.speech is not None:
            if rt.speech.started:
                # It said something ("Let me check.") and then called a tool. Close the stream
                # so nothing it says later talks over a confirmation question; the final
                # answer is then spoken whole, after the turn.
                rt.speech.abandon()
                rt.speech = None
            else:
                rt.speech.discard_pending()
        agent.conversation.append(
            {
                "role": "assistant",
                "content": reply.text,
                "tool_calls": [call.as_message_part() for call in calls],
            }
        )
        rt.proposed = calls
        return {"step": step, "go": "guard"}

    async def guard(self, state: TurnState, runtime: Any) -> TurnState:
        rt: TurnRuntime = runtime.context
        await self._enter(rt, "guard")
        screened = rt.guard.screen(rt.proposed)
        rt.proposed = []
        for outcome in screened.rejected:
            await self._settle(rt, outcome)
        queue = []
        for checked in screened.passed:
            rt.checked[checked.call.id] = checked
            queue.append(checked.call.id)
        if queue:
            return {"queue": queue, "go": "gate"}
        if state.get("handled_by") in FAST_STAGES:
            return {"go": "respond"}
        if screened.capped:
            text = "That needed more steps than I allow for one request, so I stopped."
            self._agent.conversation.append({"role": "assistant", "content": text})
            return {"reply": text, "status": "limit", "go": "respond"}
        rt.invalid_rounds += 1
        if rt.invalid_rounds > 1:  # one repair try by the model, then stop
            # Stopped, not finished: history and the benchmark count it with the step limit.
            self._agent.conversation.append({"role": "assistant", "content": GAVE_UP})
            return {"reply": GAVE_UP, "status": "limit", "go": "respond"}
        return {"go": "think"}

    async def gate(self, state: TurnState, runtime: Any) -> TurnState:
        rt: TurnRuntime = runtime.context
        queue = list(state.get("queue", []))
        call_id = queue.pop(0)
        checked = rt.checked[call_id]
        await self._enter(rt, "gate")
        rt.ctx.flags = self._flags(rt)
        executor = self._agent.executor
        try:
            gated = await executor.gate(checked, rt.ctx)
        except BaseException:
            executor.record_cancelled(checked.call, checked.started, rt.ctx)
            raise
        if isinstance(gated, CallOutcome):
            await self._settle(rt, gated, checked)
            return {"queue": queue, "current": call_id, "verdict": "done"}
        rt.gated[call_id] = gated
        verdict = "confirm" if gated.needs_confirmation else "run"
        return {"queue": queue, "current": call_id, "verdict": verdict}

    async def await_confirmation(self, state: TurnState, runtime: Any) -> TurnState:
        rt: TurnRuntime = runtime.context
        call_id = state["current"]
        gated = rt.gated[call_id]
        await self._enter(rt, "await_confirmation")
        executor = self._agent.executor
        try:
            decision = await executor.confirm(gated, rt.ctx)
        except BaseException:
            executor.record_cancelled(gated.call, gated.started, rt.ctx)
            raise
        if decision is Decision.CONFIRMED:
            rt.confirmed.add(call_id)
            return {"verdict": "run"}
        del rt.gated[call_id]
        await self._settle(rt, executor.refusal(gated, decision), rt.checked[call_id])
        return {"verdict": "done"}

    async def execute(self, state: TurnState, runtime: Any) -> TurnState:
        rt: TurnRuntime = runtime.context
        call_id = state["current"]
        gated = rt.gated.pop(call_id)
        await self._enter(rt, "execute")
        rt.times.setdefault("first_tool_ms", rt.since_start_ms())
        executor = self._agent.executor
        try:
            outcome = await executor.execute(gated, rt.ctx, confirmed=call_id in rt.confirmed)
        except BaseException:
            if gated.tool.cancel_on_interruption:  # otherwise it is audited when it finishes
                executor.record_cancelled(gated.call, gated.started, rt.ctx)
            raise
        rt.add_time("tool_ms", outcome.duration_ms)
        await self._settle(rt, outcome, rt.checked[call_id])
        return {"verdict": "done"}

    async def respond(self, state: TurnState, runtime: Any) -> TurnState:
        rt: TurnRuntime = runtime.context
        await self._enter(rt, "respond")
        if state.get("reply") is not None:
            return {}
        last = rt.last  # a fast path turn: the tool's own words are the answer
        text = DONE
        if last is not None:
            # A refusal's text is written for a model ("reply with exactly ..."); say the
            # short line ourselves.
            text = _FAST_REFUSALS.get(last.decision) or (
                last.result.speech or last.result.error or DONE
            )
        self._agent.conversation.append({"role": "assistant", "content": text})
        return {"reply": text, "status": "ok"}

    # Helpers

    async def _think_cloud(self, rt: TurnRuntime) -> TurnState | None:
        """The cloud's answer, a cloud tool step, or None to hand the turn to the local model."""
        agent = self._agent
        cloud = rt.cloud
        assert cloud is not None
        assert agent.router is not None
        limits = agent.settings.agent
        while (model := cloud.model) is not None:
            if cloud.steps >= limits.max_iterations:
                return None  # out of steps: let the local model try
            try:
                reply = await model.complete(
                    cloud.messages, cloud.schemas, private=cloud.flags.private
                )
                if not reply.tool_calls and not reply.text.strip():
                    raise LLMError("an empty reply")
            except LLMError as exc:
                agent.router.failed(model, str(exc))
                cloud.next_provider()
                continue
            except PrivacyViolation as exc:
                log.warning("Cloud turn refused: %s", exc)
                return None
            agent.router.succeeded(model, reply)
            cloud.steps += 1
            rt.add_time("llm_ms", reply.latency_ms)
            calls = reply.tool_calls[: limits.max_tool_calls_per_step]
            await self._replied(rt, reply, len(calls))
            if not calls:
                text = reply.text.strip()
                agent.conversation.append({"role": "assistant", "content": text})
                rt.model = reply.model
                rt.ctx.handled_by = CLOUD
                return {
                    "reply": text,
                    "status": "ok",
                    "step": cloud.steps,
                    "handled_by": CLOUD,
                    "go": "respond",
                }
            if any(call.name not in CLOUD_TOOLS for call in calls):
                log.info("The cloud model wanted a local tool; answering locally")
                return None
            cloud.messages.append(
                {
                    "role": "assistant",
                    "content": reply.text,
                    "tool_calls": [call.as_message_part() for call in calls],
                }
            )
            rt.ctx.handled_by = CLOUD
            rt.proposed = calls
            return {"go": "guard"}
        return None

    async def _complete(
        self, messages: list[dict[str, Any]], schemas: list[dict[str, Any]], rt: TurnRuntime
    ) -> LLMReply:
        llm = self._agent.llm
        stream = getattr(llm, "stream", None)
        if rt.speech is None or stream is None:
            reply: LLMReply = await llm.complete(messages, schemas)
        else:
            speech = rt.speech

            def on_text(delta: str) -> None:
                rt.times.setdefault("first_token_ms", rt.since_start_ms())
                speech.feed(delta)

            reply = await stream(messages, schemas, on_text=on_text)
        rt.add_time("llm_ms", reply.latency_ms)
        return reply

    async def _replied(self, rt: TurnRuntime, reply: LLMReply, calls: int) -> None:
        await self._agent.bus.publish(
            ModelReplied(
                turn_id=rt.turn_id, model=reply.model, latency_ms=reply.latency_ms, tool_calls=calls
            )
        )

    async def _settle(
        self, rt: TurnRuntime, outcome: CallOutcome, checked: Checked | None = None
    ) -> None:
        """Audit a finished call and hand its result to whichever model asked for it."""
        agent = self._agent
        rt.outcomes.append(outcome)
        rt.last = outcome
        if checked is not None:
            rt.guard.settled(checked, outcome)
        await agent.executor.finish(outcome, rt.ctx)
        message = {
            "role": "tool",
            "tool_call_id": outcome.call.id,
            "content": outcome.model_content(agent.settings.agent.max_tool_result_chars),
        }
        if rt.cloud is not None:
            rt.cloud.messages.append(message)
            rt.cloud.flags = ContextFlags(
                private=rt.cloud.flags.private or outcome.flags.private,
                untrusted=rt.cloud.flags.untrusted or outcome.flags.untrusted,
            )
        else:
            agent.conversation.append(message)
            agent.call_flags[outcome.call.id] = outcome.flags

    def _flags(self, rt: TurnRuntime) -> ContextFlags:
        return rt.cloud.flags if rt.cloud is not None else self._agent.context_flags()

    async def _enter(self, rt: TurnRuntime, node: str) -> None:
        await self._agent.bus.publish(
            AgentStateChanged(turn_id=rt.turn_id, node=node, state=NODE_STATES[node])
        )


def _go(state: TurnState) -> str:
    return state["go"]


def _after_call(state: TurnState) -> str:
    if state.get("queue"):
        return "gate"
    if state.get("handled_by") in FAST_STAGES:
        return "respond"
    return "think"


def _after_gate(state: TurnState) -> str:
    verdict = state.get("verdict")
    if verdict == "confirm":
        return "await_confirmation"
    if verdict == "run":
        return "execute"
    return _after_call(state)


def _after_answer(state: TurnState) -> str:
    return "execute" if state.get("verdict") == "run" else _after_call(state)
