"""The agent loop: ask the model, run the tools it calls, repeat until it answers or limits hit.

Each turn runs inside one asyncio task, so stopping a command is task cancellation: `cancel()`
works from any thread (stop hotkey, voice "stop", UI button) and Ctrl+C in the CLI does the same.
The steps map one to one onto LangGraph nodes if the loop moves there later (see ARCHITECTURE.md).
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from jarvis.config import Settings
from jarvis.core.channel import UserChannel
from jarvis.core.events import (
    AssistantMessage,
    EventBus,
    ModelReplied,
    TurnFinished,
    TurnStarted,
)
from jarvis.core.executor import CallOutcome, ToolExecutor
from jarvis.core.fast_path import fast_call
from jarvis.core.prompts import related_memories, system_prompt
from jarvis.core.tool_routing import ALWAYS, matched_groups, select_tools
from jarvis.llm.router import CLOUD_TOOLS, Router
from jarvis.llm.types import ChatModel, LLMError, ToolCall
from jarvis.services import Services
from jarvis.storage.repositories import HistoryLog
from jarvis.tools.base import ContextFlags, Sensitivity, ToolContext
from jarvis.tools.registry import Registry

log = logging.getLogger(__name__)

EMPTY_REPLY_NUDGE = (
    "(Your last reply was empty. Call the right tool, or answer in one short sentence.)"
)
DONE = "Done."
FAST_PATH = "fast path"  # the model name recorded for a turn no model answered
NOT_UNDERSTOOD = "Sorry, I didn't get that. Could you say it another way?"


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
        self._settings = settings
        self._llm = llm
        self._registry = registry
        self._executor = executor
        self._history = history
        self._bus = bus
        self._channel = channel
        self._services = services
        self._clock = clock
        self._router = router
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._messages: list[dict[str, Any]] = []
        self._call_flags: dict[str, ContextFlags] = {}  # tool_call_id to what its result added
        self._task: asyncio.Task[Any] | None = None
        self._task_loop: asyncio.AbstractEventLoop | None = None
        self._turn_lock = asyncio.Lock()  # one turn at a time, whichever channel started it

    @property
    def messages(self) -> list[dict[str, Any]]:
        return list(self._messages)

    @property
    def busy(self) -> bool:
        return self._task is not None and not self._task.done()

    def cancel(self) -> bool:
        """Stop the current turn. Safe to call from any thread. Returns False if idle."""
        task, loop = self._task, self._task_loop
        if task is None or loop is None or task.done():
            return False
        loop.call_soon_threadsafe(task.cancel)
        return True

    async def run_turn(
        self, text: str, source: str = "cli", timings: dict[str, int] | None = None
    ) -> TurnResult:
        """Run one command. `timings` carries stage times measured before the turn (e.g. STT).

        Voice, the web UI, and the CLI share one agent, so turns are serialized: a turn that
        arrives while another runs waits for it (callers cancel the old one first if they want).
        """
        async with self._turn_lock:
            return await self._run_turn(text, source, timings)

    async def _run_turn(self, text: str, source: str, timings: dict[str, int] | None) -> TurnResult:
        turn_id = uuid.uuid4().hex[:12]
        started = time.perf_counter()
        self._task = asyncio.current_task()
        self._task_loop = asyncio.get_running_loop()
        await self._bus.publish(TurnStarted(turn_id=turn_id, text=text, source=source))

        mark = len(self._messages)
        self._messages.append({"role": "user", "content": text})
        outcomes: list[CallOutcome] = []
        stage_times = dict(timings or {})
        iterations = 0
        model = self._llm.model
        try:
            async with asyncio.timeout(self._settings.agent.turn_timeout_s):
                cloud = None
                fast = fast_call(text)
                if fast is not None and self._registry.get(fast[0]) is None:
                    fast = None
                if fast is None and self._router is not None and self._router.wants_cloud(text):
                    cloud = await self._cloud_turn(turn_id, text, outcomes, stage_times)
                if fast is not None:
                    reply = await self._fast_turn(turn_id, *fast, outcomes, stage_times, started)
                    status, iterations, model = TurnStatus.OK, 0, FAST_PATH
                elif cloud is not None:
                    reply, iterations, model = cloud
                    status = TurnStatus.OK
                    self._messages.append({"role": "assistant", "content": reply})
                else:
                    reply, status, iterations = await self._loop(
                        turn_id, outcomes, stage_times, started
                    )
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

        if status not in (TurnStatus.OK, TurnStatus.LIMIT):
            # Drop half-finished tool exchanges so the next request is well formed.
            del self._messages[mark:]
            self._messages.append({"role": "user", "content": text})
            self._messages.append({"role": "assistant", "content": reply})
        self._trim_history()

        latency_ms = int((time.perf_counter() - started) * 1000)
        stage_times["turn_ms"] = latency_ms
        result = TurnResult(
            turn_id,
            reply,
            status,
            iterations,
            latency_ms,
            outcomes,
            timings=stage_times,
            model=model,
        )
        self._record_history(result, text, source)
        await self._bus.publish(AssistantMessage(turn_id=turn_id, text=reply))
        await self._bus.publish(
            TurnFinished(turn_id=turn_id, status=status, latency_ms=latency_ms, timings=stage_times)
        )
        return result

    async def _loop(
        self,
        turn_id: str,
        outcomes: list[CallOutcome],
        stage_times: dict[str, int],
        started: float,
    ) -> tuple[str, TurnStatus, int]:
        agent_cfg = self._settings.agent
        ctx = ToolContext(
            settings=self._settings,
            channel=self._channel,
            services=self._services,
            session_id=self.session_id,
            turn_id=turn_id,
        )
        schemas = self._tool_schemas()
        for iteration in range(1, agent_cfg.max_iterations + 1):
            reply = await self._llm.complete(self._model_messages(), schemas)
            stage_times["llm_ms"] = stage_times.get("llm_ms", 0) + reply.latency_ms
            if not reply.tool_calls and not reply.text.strip():
                # Hermes sometimes answers with nothing at all (Ollama drops a tool call it could
                # not parse). One nudge recovers it; the nudge never enters the history.
                log.info("Empty model reply in turn %s; asking once more", turn_id)
                nudge = {"role": "user", "content": EMPTY_REPLY_NUDGE}
                reply = await self._llm.complete([*self._model_messages(), nudge], schemas)
                stage_times["llm_ms"] += reply.latency_ms
            calls = reply.tool_calls[: agent_cfg.max_tool_calls_per_step]
            await self._bus.publish(
                ModelReplied(
                    turn_id=turn_id,
                    model=reply.model,
                    latency_ms=reply.latency_ms,
                    tool_calls=len(calls),
                )
            )
            if not calls:
                text = reply.text.strip() or (DONE if outcomes else NOT_UNDERSTOOD)
                self._messages.append({"role": "assistant", "content": text})
                return text, TurnStatus.OK, iteration

            self._messages.append(
                {
                    "role": "assistant",
                    "content": reply.text,
                    "tool_calls": [call.as_message_part() for call in calls],
                }
            )
            for call in calls:
                stage_times.setdefault("first_tool_ms", int((time.perf_counter() - started) * 1000))
                ctx.flags = self._context_flags()
                outcome = await self._executor.run(call, ctx)
                outcomes.append(outcome)
                self._call_flags[call.id] = outcome.flags
                self._messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": outcome.model_content(agent_cfg.max_tool_result_chars),
                    }
                )

        text = f"I couldn't finish that within {agent_cfg.max_iterations} steps, so I stopped."
        self._messages.append({"role": "assistant", "content": text})
        return text, TurnStatus.LIMIT, agent_cfg.max_iterations

    async def _fast_turn(
        self,
        turn_id: str,
        name: str,
        arguments: str,
        outcomes: list[CallOutcome],
        stage_times: dict[str, int],
        started: float,
    ) -> str:
        """Run an exact short command's tool without the model (core/fast_path.py, ADR-056).

        The exchange is kept in the history like a model's own call, so the next turn sees it
        and the context flags still count a private result.
        """
        call = ToolCall(id=f"fast_{turn_id}", name=name, arguments=arguments)
        ctx = ToolContext(
            settings=self._settings,
            channel=self._channel,
            services=self._services,
            session_id=self.session_id,
            turn_id=turn_id,
            flags=self._context_flags(),
        )
        stage_times["first_tool_ms"] = int((time.perf_counter() - started) * 1000)
        outcome = await self._executor.run(call, ctx)
        outcomes.append(outcome)
        self._call_flags[call.id] = outcome.flags
        content = outcome.model_content(self._settings.agent.max_tool_result_chars)
        reply = outcome.result.speech or outcome.result.error or DONE
        self._messages += [
            {"role": "assistant", "content": "", "tool_calls": [call.as_message_part()]},
            {"role": "tool", "tool_call_id": call.id, "content": content},
            {"role": "assistant", "content": reply},
        ]
        return reply

    async def _cloud_turn(
        self,
        turn_id: str,
        text: str,
        outcomes: list[CallOutcome],
        stage_times: dict[str, int],
    ) -> tuple[str, int, str] | None:
        """Answer with a cloud model, or None to answer locally (ADR-045).

        The cloud sees a fresh context (the system prompt and this request only: no history, no
        memories) and public read-only tools. A provider that fails hands over to the next one;
        a model that asks for anything else hands the whole turn back to the local model.
        """
        assert self._router is not None
        agent_cfg = self._settings.agent
        tools = [tool for name in CLOUD_TOOLS if (tool := self._registry.get(name)) is not None]
        schemas = [tool.schema() for tool in tools]
        now = self._clock() if self._clock else None
        for model in self._router.available():
            messages: list[dict[str, Any]] = [
                {"role": "system", "content": system_prompt(now)},
                {"role": "user", "content": text},
            ]
            flags = ContextFlags()
            ctx = ToolContext(
                settings=self._settings,
                channel=self._channel,
                services=self._services,
                session_id=self.session_id,
                turn_id=turn_id,
            )
            try:
                for iteration in range(1, agent_cfg.max_iterations + 1):
                    reply = await model.complete(messages, schemas, private=flags.private)
                    self._router.succeeded(model, reply)
                    stage_times["llm_ms"] = stage_times.get("llm_ms", 0) + reply.latency_ms
                    calls = reply.tool_calls[: agent_cfg.max_tool_calls_per_step]
                    await self._bus.publish(
                        ModelReplied(
                            turn_id=turn_id,
                            model=reply.model,
                            latency_ms=reply.latency_ms,
                            tool_calls=len(calls),
                        )
                    )
                    if not calls:
                        if not reply.text.strip():
                            raise LLMError("an empty reply")
                        return reply.text.strip(), iteration, reply.model
                    if any(call.name not in CLOUD_TOOLS for call in calls):
                        log.info("The cloud model wanted a local tool; answering locally")
                        return None
                    messages.append(
                        {
                            "role": "assistant",
                            "content": reply.text,
                            "tool_calls": [call.as_message_part() for call in calls],
                        }
                    )
                    for call in calls:
                        ctx.flags = flags
                        outcome = await self._executor.run(call, ctx)
                        outcomes.append(outcome)
                        flags = ContextFlags(
                            private=flags.private or outcome.flags.private,
                            untrusted=flags.untrusted or outcome.flags.untrusted,
                        )
                        messages.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": outcome.model_content(agent_cfg.max_tool_result_chars),
                            }
                        )
                return None  # out of steps: let the local model try
            except LLMError as exc:
                self._router.failed(model, str(exc))
        return None

    def _tool_schemas(self) -> list[dict[str, Any]]:
        """Tools for this turn, chosen from the request text (see core/tool_routing.py)."""
        if self._settings.agent.tool_routing == "all":
            return self._registry.schemas()
        request = next(m["content"] for m in reversed(self._messages) if m["role"] == "user")
        if related_memories(request, self._services.memory.texts()) and set(
            matched_groups(request)
        ) <= {"questions"}:
            # "Who is my manager" when Jarvis remembers it: offer memory, not web search, which
            # an 8B model otherwise picks over the answer it already has. Only reading: given
            # remember, the model saved the fact a second time instead of answering.
            wanted = {"list_memories", *ALWAYS}
            return [tool.schema() for tool in self._registry if tool.name in wanted]
        return [tool.schema() for tool in select_tools(request, self._registry)]

    def _context_flags(self) -> ContextFlags:
        """Whether private or outside content is in the context the model is working from.

        Computed from the messages themselves, so trimmed history and rolled-back turns drop out.
        """
        # Memories are in every local prompt, so a page could try to have them sent out too.
        private = bool(self._services.memory.texts())
        untrusted = False
        for message in self._messages:
            if message["role"] == "tool":
                flags = self._call_flags.get(message["tool_call_id"], ContextFlags())
                private = private or flags.private
                untrusted = untrusted or flags.untrusted
        return ContextFlags(private=private, untrusted=untrusted)

    def _model_messages(self) -> list[dict[str, Any]]:
        now = self._clock() if self._clock else None
        memories = self._services.memory.texts()
        messages = [{"role": "system", "content": system_prompt(now, memories)}, *self._messages]
        # An 8B model overlooks facts at the end of a long system prompt, so the ones that share
        # words with the request are repeated inside it (only in what the model sees).
        last_user = max(i for i, m in enumerate(messages) if m["role"] == "user")
        question = messages[last_user]["content"]
        relevant = related_memories(question, memories)
        if relevant:
            note = "; ".join(relevant)
            messages[last_user] = {
                "role": "user",
                "content": f"{question}\n\n(Remembered, answer from this if it fits: {note}.)",
            }
        return messages

    def _trim_history(self) -> None:
        """Keep the last N user turns. Cuts only at user messages so tool exchanges stay whole."""
        keep = self._settings.agent.history_turns + 1  # past turns plus the current one
        user_indexes = [i for i, m in enumerate(self._messages) if m["role"] == "user"]
        if len(user_indexes) > keep:
            del self._messages[: user_indexes[-keep]]
        live = {m["tool_call_id"] for m in self._messages if m["role"] == "tool"}
        self._call_flags = {k: v for k, v in self._call_flags.items() if k in live}

    def _record_history(self, result: TurnResult, text: str, source: str) -> None:
        try:
            self._history.record(
                session_id=self.session_id,
                turn_id=result.turn_id,
                source=source,
                input_text=text,
                response_text=result.text,
                status=result.status,
                model=result.model or self._llm.model,
                iterations=result.iterations,
                latency_ms=result.latency_ms,
                timings=result.timings,
            )
        except Exception:
            log.exception("Failed to record command history")
