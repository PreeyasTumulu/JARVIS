"""The reply as sentences while the model is still writing it, so speech starts on the first one.

Home Assistant took its first audio from 5.31 s to 0.56 s this way (docs/RESEARCH.md 6.2). The
voice session makes one `SpeechStream` per turn and speaks `sentences()` as they arrive; the
agent feeds it text from a streaming model reply and closes it at the end of the turn. A reply
that turns out to be a tool call is never fed: the model client holds text back until it can
tell (llm/client.py).
"""

from __future__ import annotations

import asyncio
import re
import time
from collections.abc import AsyncIterator

_END = re.compile(r"(?<=[.!?])\s+")  # a sentence ends at . ! or ? followed by a space
MIN_CHARS = 20  # shorter pieces are joined to the next, as split_sentences does for Piper


class SpeechStream:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[str | None] = asyncio.Queue()
        self._buffer = ""
        self._closed = False
        self.text = ""  # everything handed out as sentences so far
        self.first_sentence_at: float | None = None  # perf_counter when the first one was ready

    @property
    def started(self) -> bool:
        return self.first_sentence_at is not None

    @property
    def closed(self) -> bool:
        return self._closed

    def feed(self, delta: str) -> None:
        """More reply text. Complete sentences go out; the rest waits for more."""
        if self._closed or not delta:
            return
        self._buffer += delta
        pieces = _END.split(self._buffer)
        ready, self._buffer = pieces[:-1], pieces[-1]
        pending = ""
        for piece in ready:
            pending = f"{pending} {piece}".strip()
            if len(pending) >= MIN_CHARS:
                self._emit(pending)
                pending = ""
        if pending:
            self._buffer = f"{pending} {self._buffer}".strip()

    def add(self, text: str) -> None:
        """A whole extra sentence after the reply (the briefing offer)."""
        self.feed(f" {text} ")

    def finish(self) -> None:
        """The reply is complete: say what is left."""
        if self._closed:
            return
        tail = self._buffer.strip()
        self._buffer = ""
        if tail:
            self._emit(tail)
        self._close()

    def discard_pending(self) -> None:
        """Drop text not yet sent: the model went on to call a tool after writing it."""
        self._buffer = ""

    def abandon(self) -> None:
        """Nothing more will be said through this stream (unsent text is dropped)."""
        self._buffer = ""
        self._close()

    async def sentences(self) -> AsyncIterator[str]:
        while True:
            sentence = await self._queue.get()
            if sentence is None:
                return
            yield sentence

    def _emit(self, sentence: str) -> None:
        if self.first_sentence_at is None:
            self.first_sentence_at = time.perf_counter()
        self.text = f"{self.text} {sentence}".strip()
        self._queue.put_nowait(sentence)

    def _close(self) -> None:
        if not self._closed:
            self._closed = True
            self._queue.put_nowait(None)
