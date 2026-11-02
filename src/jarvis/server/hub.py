"""Connected browser tabs: events fan out to every tab, and answers can come back from any of them.

Every message to the browser is JSON with a `type`. Bus events keep their field names and get a
snake_case type (`ToolCallStarted` becomes `tool_call_started`), so the protocol follows the
events instead of a second hand-written list. Open confirmation cards and questions are kept and
replayed to a tab that connects (or reloads) while they wait.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import asdict
from typing import Any

from jarvis.core.channel import ConfirmationRequest
from jarvis.core.events import ConfirmationRequested, ConfirmationResolved, Event

log = logging.getLogger(__name__)

MAX_QUEUE = 1000  # messages waiting for one slow tab before it is dropped
_CAMEL = re.compile(r"(?<!^)(?=[A-Z])")

Message = dict[str, Any]


def event_message(event: Event) -> Message:
    """A bus event as a WebSocket message."""
    return {"type": _CAMEL.sub("_", type(event).__name__).lower(), **asdict(event)}


class Client:
    """One browser tab. Messages queue up and a pump task sends them in order."""

    def __init__(self, send_text: Callable[[str], Awaitable[None]]) -> None:
        self._send_text = send_text
        self._queue: asyncio.Queue[Message] = asyncio.Queue(MAX_QUEUE)
        self.dropped = False

    def send(self, message: Message) -> None:
        try:
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            self.dropped = True  # the pump notices and ends the connection

    async def pump(self) -> None:
        while not self.dropped:
            message = await self._queue.get()
            await self._send_text(json.dumps(message, ensure_ascii=False, default=str))


class WebHub:
    def __init__(self) -> None:
        self._clients: set[Client] = set()
        self._confirms: dict[str, asyncio.Future[bool]] = {}
        self._questions: dict[str, asyncio.Future[str]] = {}
        self._open: dict[str, Message] = {}  # confirmation cards and questions still waiting

    @property
    def client_count(self) -> int:
        return len(self._clients)

    def connect(self, client: Client) -> None:
        self._clients.add(client)

    def disconnect(self, client: Client) -> None:
        self._clients.discard(client)

    def broadcast(self, message: Message) -> None:
        for client in list(self._clients):
            client.send(message)

    def open_items(self) -> list[Message]:
        return list(self._open.values())

    def on_event(self, event: Event) -> None:
        """Event bus subscriber."""
        message = event_message(event)
        if isinstance(event, ConfirmationRequested):
            self._open[event.request.request_id] = message
        elif isinstance(event, ConfirmationResolved):
            self._open.pop(event.request_id, None)
        self.broadcast(message)

    def resolve(self, request_id: str, approved: bool) -> bool:
        """A Confirm or Cancel click. False if nothing is waiting under that id."""
        future = self._confirms.get(request_id)
        if future is None or future.done():
            return False
        future.set_result(approved)
        return True

    def answer(self, question_id: str, text: str) -> bool:
        future = self._questions.get(question_id)
        if future is None or future.done():
            return False
        future.set_result(text)
        return True


class WebChannel:
    """The browser as a UserChannel. Any open tab can answer; no tab means no answer (timeout)."""

    name = "web"

    def __init__(self, hub: WebHub) -> None:
        self._hub = hub

    async def confirm(self, request: ConfirmationRequest) -> bool:
        # The card itself comes from the ConfirmationRequested event the executor publishes.
        future: asyncio.Future[bool] = asyncio.get_running_loop().create_future()
        self._hub._confirms[request.request_id] = future
        try:
            return await future
        finally:
            self._hub._confirms.pop(request.request_id, None)

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        question_id = uuid.uuid4().hex[:12]
        message: Message = {
            "type": "question",
            "question_id": question_id,
            "question": question,
            "options": list(options or []),
        }
        future: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        self._hub._questions[question_id] = future
        self._hub._open[question_id] = message
        self._hub.broadcast(message)
        try:
            return await future
        finally:
            self._hub._questions.pop(question_id, None)
            self._hub._open.pop(question_id, None)
            self._hub.broadcast({"type": "question_closed", "question_id": question_id})
