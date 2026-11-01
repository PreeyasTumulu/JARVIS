"""Decides what the overlay shows, from bus events. No graphics here, so it is easy to test.

The overlay answers the voice. It opens when you start talking to Jarvis or when Jarvis waits for
your answer. Typed commands, dictation, and spoken reminders never open it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from jarvis.core.events import (
    AssistantMessage,
    ConfirmationRequested,
    ConfirmationResolved,
    Event,
    ToolCallFinished,
    ToolCallStarted,
    TranscriptHeard,
    TranscriptPartial,
    VoiceLevel,
    VoiceStateChanged,
)

Message = dict[str, Any]

REPLY_LINGER_S = 3.0  # keep the answer on screen for a moment after Jarvis stops speaking
HEADINGS = {
    "listening": "Listening",
    "transcribing": "Got it",
    "thinking": "Thinking",
    "speaking": "Jarvis",
    "awaiting_answer": "Waiting for your answer",
}
OPENING_STATES = ("listening", "awaiting_answer")
RESTING_STATES = ("idle", "muted", "off")


class Director:
    def __init__(self, send: Callable[[Message], None]) -> None:
        self._send = send
        self._active = False
        self._dictating = False
        self._state = "idle"
        self._body = ""
        self._status = ""
        self._question = ""
        self._replied = False

    @property
    def active(self) -> bool:
        return self._active

    def on_event(self, event: Event) -> None:
        """Event bus subscriber."""
        match event:
            case VoiceStateChanged(state=state, detail=detail):
                self._on_state(state, detail)
            case VoiceLevel(level=level) if self._active:
                self._send({"t": "level", "v": round(level, 3)})
            case TranscriptPartial(text=text) if self._active:
                self._body = text
                self._show()
            case TranscriptHeard(text=text) if self._active:
                self._body = text
                self._show()
            case ToolCallStarted(tool=tool) if self._active:
                self._status = f"Running {tool}"  # the tool's name only, never its arguments
                self._show()
            case ToolCallFinished() if self._active:
                self._status = ""
                self._show()
            case AssistantMessage(text=text) if self._active:
                self._body = text
                self._status = ""
                self._replied = True
                self._show()
            case ConfirmationRequested(request=request):
                self._question = request.summary  # the prepared call, the same words voice reads
                if self._active:
                    self._show()
            case ConfirmationResolved():
                self._question = ""
                if self._active:
                    self._show()
            case _:
                pass

    def _on_state(self, state: str, detail: str) -> None:
        if detail.startswith("dictat"):
            self._dictating = True  # text for the focused app: stay out of the way
            return
        if self._dictating and state in RESTING_STATES:
            self._dictating = False
            return
        self._dictating = False
        self._state = state
        if state in RESTING_STATES:
            if self._active:
                self._active = False
                linger = REPLY_LINGER_S if self._replied and detail != "stopped" else 0.0
                self._send({"t": "hide", "after": linger})
            self._reset()
            return
        if state in OPENING_STATES and not self._active:
            self._active = True
            self._body = ""
            self._status = ""
            self._replied = False
            self._send({"t": "wake"})
        if self._active:
            self._send({"t": "state", "state": state})
            self._show()

    def _show(self) -> None:
        heading = HEADINGS.get(self._state, "")
        tone = "normal"
        body = self._body
        if self._question:
            heading, tone, body = "Say yes or no", "confirm", self._question
        self._send(
            {"t": "text", "heading": heading, "body": body, "status": self._status, "tone": tone}
        )

    def _reset(self) -> None:
        self._body = ""
        self._status = ""
        self._question = ""
        self._replied = False
