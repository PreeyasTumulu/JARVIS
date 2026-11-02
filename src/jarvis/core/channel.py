"""The interface every input channel (CLI, voice, web UI) implements to talk back to the user."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar

T = TypeVar("T")

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfirmationRequest:
    request_id: str
    tool: str
    summary: str  # exactly what will happen, for example "Open Spotify"
    digest: str  # hash of the prepared arguments this approval is bound to
    reason: str | None
    timeout_s: float


class UserChannel(Protocol):
    @property
    def name(self) -> str:
        """Recorded in the audit log as the confirming channel."""
        ...

    async def confirm(self, request: ConfirmationRequest) -> bool:
        """Return True only on an explicit yes."""
        ...

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        """Ask a clarifying question and return the answer text."""
        ...


class FirstAnswerChannel:
    """Asks every channel at once (for example voice and the web UI). The first answer wins.

    A channel that fails (voice without a working microphone) drops out of the race instead of
    ending it; only when every channel fails does the error reach the caller.
    """

    def __init__(self, *channels: UserChannel) -> None:
        if not channels:
            raise ValueError("FirstAnswerChannel needs at least one channel")
        self._channels = channels
        self._last: str | None = None

    @property
    def name(self) -> str:
        return self._last or "+".join(channel.name for channel in self._channels)

    async def confirm(self, request: ConfirmationRequest) -> bool:
        return await self._race(lambda channel: channel.confirm(request))

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        return await self._race(lambda channel: channel.ask(question, options))

    async def _race(self, call: Callable[[UserChannel], Awaitable[T]]) -> T:
        tasks = {asyncio.ensure_future(call(channel)): channel for channel in self._channels}
        pending = set(tasks)
        winner: asyncio.Task[T] | None = None
        try:
            while pending and winner is None:
                done, pending = await asyncio.wait(pending, return_when=asyncio.FIRST_COMPLETED)
                for task in done:
                    if task.exception() is None:
                        winner = task
                        break
                    log.debug("Channel %s dropped out: %r", tasks[task].name, task.exception())
        finally:
            for task in tasks:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
        if winner is None:
            return next(iter(tasks)).result()  # every channel failed: raise the first error
        self._last = tasks[winner].name
        return winner.result()
