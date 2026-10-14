"""The text-to-speech interface. Engines: SAPI now, Piper and Kokoro in Phase 2."""

from __future__ import annotations

from typing import Protocol


class TTSEngine(Protocol):
    async def speak(self, text: str) -> None:
        """Speak the text and return when finished. Cancelling the call stops speech."""
        ...

    async def stop(self) -> None:
        """Stop any speech in progress."""
        ...
