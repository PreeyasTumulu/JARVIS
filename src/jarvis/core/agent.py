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
from jarvis.core.prompts import system_prompt
from jarvis.llm.types import ChatModel, LLMError
from jarvis.services import Services
from jarvis.storage.repositories import HistoryLog
from jarvis.tools.base import Sensitivity, ToolContext
from jarvis.tools.registry import Registry

log = logging.getLogger(__name__)


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
        self.session_id = session_id or uuid.uuid4().hex[:12]
        self._messages: list[dict[str, Any]] = []
        self._task: asyncio.Task[Any] | None = None
        self._task_loop: asyncio.AbstractEventLoop | None = None

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
        """Run one command. `timings` carries stage times measured before the turn (e.g. STT)."""
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
        try:
            async with asyncio.timeout(self._settings.agent.turn_timeout_s):
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
            turn_id, reply, status, iterations, latency_ms, outcomes, timings=stage_times
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
        for iteration in range(1, agent_cfg.max_iterations + 1):
            reply = await self._llm.complete(self._model_messages(), self._registry.schemas())
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
                text = reply.text.strip() or "Done."
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
                outcome = await self._executor.run(call, ctx)
                outcomes.append(outcome)
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

    def _model_messages(self) -> list[dict[str, Any]]:
        now = self._clock() if self._clock else None
        return [{"role": "system", "content": system_prompt(now)}, *self._messages]

    def _trim_history(self) -> None:
        """Keep the last N user turns. Cuts only at user messages so tool exchanges stay whole."""
        keep = self._settings.agent.history_turns + 1  # past turns plus the current one
        user_indexes = [i for i, m in enumerate(self._messages) if m["role"] == "user"]
        if len(user_indexes) > keep:
            del self._messages[: user_indexes[-keep]]

    def _record_history(self, result: TurnResult, text: str, source: str) -> None:
        try:
            self._history.record(
                session_id=self.session_id,
                turn_id=result.turn_id,
                source=source,
                input_text=text,
                response_text=result.text,
                status=result.status,
                model=self._llm.model,
                iterations=result.iterations,
                latency_ms=result.latency_ms,
                timings=result.timings,
            )
        except Exception:
            log.exception("Failed to record command history")
