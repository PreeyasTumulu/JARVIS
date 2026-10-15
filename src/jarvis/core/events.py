"""Typed events and a tiny async pub/sub bus. The CLI, web UI, and TTS subscribe to these."""

from __future__ import annotations

import inspect
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from jarvis.core.channel import ConfirmationRequest

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class TurnStarted:
    turn_id: str
    text: str
    source: str


@dataclass(frozen=True)
class ModelReplied:
    turn_id: str
    model: str
    latency_ms: int
    tool_calls: int


@dataclass(frozen=True)
class ToolCallStarted:
    turn_id: str
    call_id: str
    tool: str
    args: dict[str, Any]
    risk: str


@dataclass(frozen=True)
class ConfirmationRequested:
    turn_id: str
    request: ConfirmationRequest


@dataclass(frozen=True)
class ConfirmationResolved:
    turn_id: str
    request_id: str
    decision: str  # confirmed, denied, timeout, or cancelled
    via: str | None = None  # the channel that answered


@dataclass(frozen=True)
class ToolCallFinished:
    turn_id: str
    call_id: str
    tool: str
    decision: str
    ok: bool
    summary: str
    duration_ms: int


@dataclass(frozen=True)
class AssistantMessage:
    turn_id: str
    text: str


@dataclass(frozen=True)
class TurnFinished:
    turn_id: str
    status: str
    latency_ms: int
    timings: dict[str, int] | None = None


@dataclass(frozen=True)
class VoiceStateChanged:
    state: str  # idle, listening, transcribing, thinking, speaking, awaiting_answer
    detail: str = ""


@dataclass(frozen=True)
class TranscriptHeard:
    text: str
    audio_ms: int
    stt_ms: int


@dataclass(frozen=True)
class NotificationsArrived:
    count: int
    apps: tuple[str, ...]  # app names only; the text stays in the database (private)


@dataclass(frozen=True)
class ReminderDue:
    reminder_id: int
    kind: str  # timer or reminder
    text: str  # what Jarvis says


Event = (
    TurnStarted
    | ModelReplied
    | ToolCallStarted
    | ConfirmationRequested
    | ConfirmationResolved
    | ToolCallFinished
    | AssistantMessage
    | TurnFinished
    | VoiceStateChanged
    | TranscriptHeard
    | ReminderDue
    | NotificationsArrived
)
Handler = Callable[[Event], Awaitable[None] | None]


class EventBus:
    def __init__(self) -> None:
        self._handlers: list[Handler] = []

    def subscribe(self, handler: Handler) -> Callable[[], None]:
        self._handlers.append(handler)
        return lambda: self._handlers.remove(handler)

    async def publish(self, event: Event) -> None:
        for handler in list(self._handlers):
            try:
                result = handler(event)
                if inspect.isawaitable(result):
                    await result
            except Exception:
                # A broken subscriber must never break the agent.
                log.exception("Event handler failed for %s", type(event).__name__)
