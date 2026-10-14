"""Piper text to speech (optional extra, GPL-3.0, never bundled; see ADR-006).

Speaks sentence by sentence: the next sentence is synthesized while the current one plays, and
stop() cuts playback within about 50 ms.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import re
import threading
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.voice.audio import Audio, AudioPlayer
from jarvis.voice.models import ensure_piper_voice

log = logging.getLogger(__name__)

_SENTENCE_END = re.compile(r"(?<=[.!?;:])\s+")


def split_sentences(text: str, min_chars: int = 20) -> list[str]:
    """Split into sentences, merging very short ones so speech does not sound choppy."""
    pieces = [p.strip() for p in _SENTENCE_END.split(text.strip()) if p.strip()]
    merged: list[str] = []
    for piece in pieces:
        if merged and len(merged[-1]) < min_chars:
            merged[-1] = f"{merged[-1]} {piece}"
        else:
            merged.append(piece)
    return merged


class PiperTTS:
    def __init__(
        self,
        voice: str,
        models_dir: Path,
        *,
        speed: float = 1.0,
        player: AudioPlayer | None = None,
    ) -> None:
        self._voice_name = voice
        self._models_dir = models_dir
        self._speed = speed
        self._player = player or AudioPlayer()
        self._voice: Any = None
        self._load_lock = threading.Lock()
        self._generation = 0  # bumped by stop() so an in-progress speak() gives up

    def load(self) -> None:
        with self._load_lock:
            if self._voice is not None:
                return
            from piper import PiperVoice

            path = ensure_piper_voice(self._models_dir, self._voice_name)
            self._voice = PiperVoice.load(path)

    def synthesize(self, text: str) -> tuple[Audio, int]:
        """Blocking. Returns (int16 samples, sample rate)."""
        self.load()
        from piper import SynthesisConfig

        config = SynthesisConfig(length_scale=1.0 / self._speed)
        chunks = list(self._voice.synthesize(text, syn_config=config))
        if not chunks:
            return np.zeros(0, dtype=np.int16), 22_050
        audio = np.concatenate([chunk.audio_int16_array for chunk in chunks]).astype(np.int16)
        return audio, int(chunks[0].sample_rate)

    async def speak(self, text: str) -> None:
        sentences = split_sentences(text)
        if not sentences:
            return
        generation = self._generation
        pending = asyncio.ensure_future(asyncio.to_thread(self.synthesize, sentences[0]))
        try:
            for index in range(len(sentences)):
                audio, rate = await pending
                if index + 1 < len(sentences):
                    pending = asyncio.ensure_future(
                        asyncio.to_thread(self.synthesize, sentences[index + 1])
                    )
                if generation != self._generation:
                    return
                finished = await asyncio.to_thread(self._player.play, audio, rate)
                if not finished or generation != self._generation:
                    return
        except asyncio.CancelledError:
            self._player.stop()
            raise
        finally:
            if not pending.done():
                pending.cancel()
                with contextlib.suppress(asyncio.CancelledError, Exception):
                    await pending

    async def stop(self) -> None:
        self._generation += 1
        self._player.stop()
