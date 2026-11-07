"""The text-to-speech interface. Engines: Piper (optional extra) and Windows SAPI."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator
from typing import Protocol


class TTSEngine(Protocol):
    async def speak(self, text: str) -> None:
        """Speak the text and return when finished. Cancelling the call stops speech."""
        ...

    async def stop(self) -> None:
        """Stop any speech in progress."""
        ...


async def speak_stream(tts: TTSEngine, sentences: AsyncIterator[str]) -> float | None:
    """Speak sentences as they arrive; the perf_counter time the first one started, or None.

    Piper has its own `speak_stream`, which makes the next sentence while one plays. Any other
    engine (SAPI) speaks each sentence once it arrives, which still starts on the first one.
    """
    own = getattr(tts, "speak_stream", None)
    if own is not None:
        started: float | None = await own(sentences)
        return started
    first: float | None = None
    async for sentence in sentences:
        if first is None:
            first = time.perf_counter()
        await tts.speak(sentence)
    return first
