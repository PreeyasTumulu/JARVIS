"""The agent: one conversation, whose turns run through the LangGraph graph in core/graph.py.

Each turn runs inside one asyncio task, so stopping a command is task cancellation: `cancel()`
works from any thread (stop hotkey, voice "stop", the API) and Ctrl+C in the CLI does the same.
The agent keeps what lasts between turns (the conversation, what is private in it, the
briefing offer); the graph decides what happens within one.
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.config import Settings
from jarvis.core.channel import UserChannel
from jarvis.core.events import AssistantMessage, EventBus, TurnFinished, TurnStarted
from jarvis.core.executor import CallOutcome, ToolExecutor
from jarvis.core.graph import AgentGraph, TurnRuntime
from jarvis.core.guard import Guard
from jarvis.core.pipeline import AGENT, FAST_STAGES
from jarvis.core.prompts import system_prompt
from jarvis.core.speech import SpeechStream
from jarvis.core.tool_routing import ALWAYS, matched_groups, needs_meaning, select_tools
from jarvis.llm.router import Router
from jarvis.llm.types import ChatModel, LLMError
from jarvis.services import Services
from jarvis.storage.repositories import HistoryLog
from jarvis.tools.base import ContextFlags, Sensitivity, ToolContext
from jarvis.tools.mcp.tools import register_all
from jarvis.tools.recall import FORGET_HISTORY, after_turn, relevant_memories
from jarvis.tools.registry import Registry

log = logging.getLogger(__name__)

FAST_PATH = "fast path"  # the model name recorded for a turn no model answered
BRIEFING_OFFER = "By the way, would you like your morning briefing?"
OFFERED_KEY = "briefing.offered_on"  # the day the briefing was last offered


class TurnStatus(StrEnum):
    OK = "ok"
    CANCELLED = "cancelled"
    TIMEOUT = "timeout"
    LIMIT = "limit"
    ERROR = "error"


@dataclass
class TurnResult:
    turn_id: str
    text: str
    status: TurnStatus
    iterations: int
    latency_ms: int
    outcomes: list[CallOutcome] = field(default_factory=list)
    timings: dict[str, int] = field(default_factory=dict)
    model: str = ""  # the model that wrote the final answer
    handled_by: str = AGENT  # the router stage that answered (ADR-083)
    spoken: bool = False  # the reply was already spoken sentence by sentence as it was written

    @property
    def sensitivity(self) -> Sensitivity:
        return Sensitivity.highest(Sensitivity.PUBLIC, *(o.sensitivity for o in self.outcomes))


class Agent:
    def __init__(
        self,
        *,
        settings: Settings,
        llm: ChatModel,
        registry: Registry,
        executor: ToolExecutor,
        history: HistoryLog,
        bus: EventBus,
        channel: UserChannel,
        services: Services,
        session_id: str | None = None,
        clock: Callable[[], datetime] | None = None,
        router: Router | None = None,
    ) -> None:
        self.settings = settings
        self.llm = llm
        self.registry = registry
        self.executor = executor
        self.bus = bus
        self.services = services
        self.router = router
        self._history = history
        self._channel = channel
        self._clock = clock
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self.conversation: list[dict[str, Any]] = []  # what the local model sees, minus prompt
        self.call_flags: dict[str, ContextFlags] = {}  # tool_call_id to what its result added
        self._graph = AgentGraph(self)
        self._task: asyncio.Task[Any] | None = None
        self._task_loop: asyncio.AbstractEventLoop | None = None
        self._turn_lock = asyncio.Lock()  # one turn at a time, whichever channel started it
        self._relevant: list[str] = []  # memories that fit the current request (ADR-065)
        self._offer_pending = False  # the last reply offered the briefing (ADR-066)
        self._mcp_ready = False
        self._background: set[asyncio.Task[None]] = set()

    @property
    def messages(self) -> list[dict[str, Any]]:
        return list(self.conversation)

    @property
    def graph(self) -> AgentGraph:
        return self._graph

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def now(self) -> datetime | None:
        return self._clock() if self._clock else None

    def cancel(self) -> bool:
        """Stop the current turn. Safe to call from any thread. Returns False if idle."""
        task, loop = self._task, self._task_loop
        if task is None or loop is None or task.done():
            return False
        loop.call_soon_threadsafe(task.cancel)
        return True

    async def prepare_tools(self) -> list[str]:
        """Connect the MCP servers once and register their listed tools (ADR-059).

        `jarvis serve` calls this at startup; otherwise the first turn does. A server that
        fails is skipped, so this never raises.
        """
        if self._mcp_ready:
            return []
        self._mcp_ready = True
        hub = self.services.mcp
        if not hub.configured():
            return []
        try:
            remotes = await hub.start()
        except Exception:
            log.exception("MCP servers could not start")
            return []
        return register_all(self.registry, hub, remotes, hub.configured())

    def warm_up(self) -> None:
        """Build the graph and open the vector store now (LangGraph takes about 2.5 s to
        import and ChromaDB about 1 s), so the first request does not wait for them."""
        started = time.perf_counter()
        self._graph.compiled()
        if self.services.meaning is not None:
            self.services.meaning.open()
        log.info("Warmed up in %d ms", (time.perf_counter() - started) * 1000)

    def warm_up_in_background(self) -> threading.Thread:
        """Warm up in a thread, so the prompt or the server is ready at once."""

        def warm() -> None:
            try:
                self.warm_up()
            except Exception:
                log.exception("Warm-up failed; the first request builds what it needs")

        thread = threading.Thread(target=warm, name="jarvis-warm-up", daemon=True)
        thread.start()
        return thread

    async def run_turn(
        self,
        text: str,
        source: str = "cli",
        timings: dict[str, int] | None = None,
        speech: SpeechStream | None = None,
    ) -> TurnResult:
        """Run one command. `timings` carries stage times measured before the turn (e.g. STT).

        With `speech`, a reply the model writes is fed to it sentence by sentence as it is
        written, and the stream is closed when the turn ends (`TurnResult.spoken` says whether
        anything went out). Voice, the API, and the CLI share one agent, so turns are
        serialized: a turn that arrives while another runs waits for it.
        """
        async with self._turn_lock:
            await self.prepare_tools()
            self._relevant = await relevant_memories(self.services, text)
            try:
                return await self._run_turn(text, source, timings, speech)
            finally:
                if speech is not None:
                    speech.abandon()  # closes it if the turn did not

    async def _run_turn(
        self,
        text: str,
        source: str,
        timings: dict[str, int] | None,
        speech: SpeechStream | None,
    ) -> TurnResult:
        turn_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        self._task = asyncio.current_task()
        self._task_loop = asyncio.get_running_loop()
        await self.bus.publish(TurnStarted(turn_id=turn_id, text=text, source=source))

        mark = len(self.conversation)
        self.conversation.append({"role": "user", "content": text})
        offer_pending, self._offer_pending = self._offer_pending, False
        ctx = ToolContext(
            settings=self.settings,
            channel=self._channel,
            services=self.services,
            session_id=self.session_id,
            turn_id=turn_id,
        )
        rt = TurnRuntime(
            turn_id=turn_id,
            text=text,
            ctx=ctx,
            guard=Guard(self.executor, self.settings.agent.max_tool_calls_per_turn),
            started=started,
            times=dict(timings or {}),
            speech=speech,
            offer_pending=offer_pending,
            model=self.llm.model,
        )
        iterations = 0
        handled_by = AGENT
        try:
            async with asyncio.timeout(self.settings.agent.turn_timeout_s):
                state = await self._graph.run(rt)
            reply = state.get("reply") or ""
            status = TurnStatus(state.get("status", "ok"))
            handled_by = state.get("handled_by", AGENT)
            iterations = state.get("step", 0)
        except TimeoutError:
            reply, status = "That took too long, so I stopped.", TurnStatus.TIMEOUT
        except asyncio.CancelledError:
            task = asyncio.current_task()
            if task is not None:
                task.uncancel()  # the turn is the unit of cancellation; the session carries on
            reply, status = "Stopped.", TurnStatus.CANCELLED
        except LLMError as exc:
            reply, status = str(exc), TurnStatus.ERROR
        except Exception:
            log.exception("Turn %s failed", turn_id)
            reply = "Something went wrong on my side. The details are in the log file."
            status = TurnStatus.ERROR
        finally:
            self._task = None

        fast = handled_by in FAST_STAGES
        if status not in (TurnStatus.OK, TurnStatus.LIMIT):
            # Drop half-finished tool exchanges so the next request is well formed.
            del self.conversation[mark:]
            self.conversation.append({"role": "user", "content": text})
            self.conversation.append({"role": "assistant", "content": reply})
        if status is TurnStatus.OK and self._should_offer(rt.outcomes):
            reply = f"{reply} {BRIEFING_OFFER}"
            self._offer_pending = True
            if speech is not None and speech.started and not speech.closed:
                speech.add(BRIEFING_OFFER)
        spoken = False
        streaming = speech is not None and speech.started and not speech.closed
        if speech is not None and streaming and status is TurnStatus.OK and not fast:
            speech.finish()
            spoken = True
        forgot = any(o.call.name == FORGET_HISTORY and o.result.ok for o in rt.outcomes)
        if forgot:
            del self.conversation[:mark]  # what was deleted must not stay in the conversation
        self._trim_history()

        latency_ms = int((time.perf_counter() - started) * 1000)
        rt.times["turn_ms"] = latency_ms
        result = TurnResult(
            turn_id,
            reply,
            status,
            0 if fast else iterations,
            latency_ms,
            rt.outcomes,
            timings=rt.times,
            model=FAST_PATH if fast else rt.model or self.llm.model,
            handled_by=handled_by,
            spoken=spoken,
        )
        if not forgot:  # "forget what I asked about my doctor" would keep the word "doctor"
            self._record_history(result, text, source)
        await self.bus.publish(AssistantMessage(turn_id=turn_id, text=reply))
        await self.bus.publish(
            TurnFinished(turn_id=turn_id, status=status, latency_ms=latency_ms, timings=rt.times)
        )
        # Memory work comes after the answer is out, never on the reply path (ADR-084).
        self._spawn(after_turn(self.services))
        return result

    def add_timings(self, turn_id: str, extra: dict[str, int]) -> None:
        """Stage times measured after the turn (first audio), added to its history row."""
        try:
            self._history.add_timings(turn_id, extra)
        except Exception:
            log.exception("Failed to add timings to turn %s", turn_id)

    async def drain(self) -> None:
        """Wait for background memory work and tools left running after a stop."""
        while self._background:
            await asyncio.gather(*list(self._background), return_exceptions=True)
        await self.executor.drain()

    def _spawn(self, coro: Any) -> None:
        task: asyncio.Task[None] = asyncio.ensure_future(coro)
        self._background.add(task)
        task.add_done_callback(self._background.discard)

    def _should_offer(self, outcomes: list[CallOutcome]) -> bool:
        """Offer the briefing once a day, on the first command of the morning (ADR-066)."""
        cfg = self.settings.briefing
        prefs = self.services.prefs
        if not cfg.offer or prefs is None or self.registry.get("briefing") is None:
            return False
        now = self._clock() if self._clock else datetime.now().astimezone()
        if any(o.call.name == "briefing" for o in outcomes):
            prefs.set(OFFERED_KEY, now.date().isoformat())  # heard it: no offer today
            return False
        if not cfg.offer_from_hour <= now.hour < cfg.offer_until_hour:
            return False
        today = now.date().isoformat()
        if prefs.get(OFFERED_KEY) == today:
            return False
        prefs.set(OFFERED_KEY, today)
        return True

    async def tool_schemas(self) -> list[dict[str, Any]]:
        """Tools for this turn, chosen from the request text (see core/tool_routing.py)."""
        if self.settings.agent.tool_routing == "all":
            return self.registry.schemas()
        request = next(m["content"] for m in reversed(self.conversation) if m["role"] == "user")
        if self._relevant and set(matched_groups(request)) <= {"questions"}:
            # "Who is my manager" when Jarvis remembers it: offer memory, not web search, which
            # an 8B model otherwise picks over the answer it already has. Only reading: given
            # remember, the model saved the fact a second time instead of answering.
            wanted = {"list_memories", *ALWAYS}
            return [tool.schema() for tool in self.registry if tool.name in wanted]
        meant: list[str] = []
        semantic = self.services.semantic
        if semantic is not None and needs_meaning(request, self.registry):
            meant = await semantic.groups(request)
            if meant:
                log.info("Routed by meaning to %s", ", ".join(meant))
        return [tool.schema() for tool in select_tools(request, self.registry, meant)]

    def context_flags(self) -> ContextFlags:
        """Whether private or outside content is in the context the model is working from.

        Computed from the messages themselves, so trimmed history and rolled-back turns drop out.
        """
        # Memories are in every local prompt, so a page could try to have them sent out too.
        private = bool(self.services.memory.texts())
        untrusted = False
        for message in self.conversation:
            if message["role"] == "tool":
                flags = self.call_flags.get(message["tool_call_id"], ContextFlags())
                private = private or flags.private
                untrusted = untrusted or flags.untrusted
        return ContextFlags(private=private, untrusted=untrusted)

    def model_messages(self) -> list[dict[str, Any]]:
        memories = self.services.memory.prompt_texts(self.settings.memory)
        messages = [{"role": "system", "content": system_prompt(self.now(), memories)}]
        messages += self.conversation
        # An 8B model overlooks facts at the end of a long system prompt, so the ones that share
        # words with the request are repeated inside it (only in what the model sees).
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        question = messages[last_user]["content"]
        relevant = self._relevant
        if relevant:
            note = "; ".join(relevant)
            messages[last_user] = {
                "role": "user",
                "content": f"{question}\n\n(Remembered, answer from this if it fits: {note}.)",
            }
        return messages

    def _trim_history(self) -> None:
        """Keep the last N user turns. Cuts only at user messages so tool exchanges stay whole."""
        keep = self.settings.agent.history_turns + 1  # past turns plus the current one
        user_indexes = [i for i, m in enumerate(self.conversation) if m["role"] == "user"]
        if len(user_indexes) > keep:
            del self.conversation[: user_indexes[-keep]]
        live = {m["tool_call_id"] for m in self.conversation if m["role"] == "tool"}
        self.call_flags = {k: v for k, v in self.call_flags.items() if k in live}

    def _record_history(self, result: TurnResult, text: str, source: str) -> None:
        try:
            self._history.record(
                session_id=self.session_id,
                turn_id=result.turn_id,
                source=source,
                input_text=text,
                response_text=result.text,
                status=result.status,
                model=result.model or self.llm.model,
                iterations=result.iterations,
                latency_ms=result.latency_ms,
                timings=result.timings,
                handled_by=result.handled_by,
            )
        except Exception:
            log.exception("Failed to record command history")
