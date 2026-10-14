"""End-of-speech detection from per-frame voice probabilities. Pure logic, easy to test."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Endpoint(StrEnum):
    CONTINUE = "continue"
    DONE = "done"  # speech, then enough silence
    TOO_LONG = "too_long"  # hit the maximum length while speaking
    NO_SPEECH = "no_speech"  # nothing said before the timeout


@dataclass
class Endpointer:
    frame_ms: int
    threshold: float = 0.5
    end_silence_ms: int = 800
    max_ms: int = 12_000
    no_speech_ms: int = 5_000
    min_speech_ms: int = 160
    elapsed_ms: int = field(default=0, init=False)
    speech_ms: int = field(default=0, init=False)
    silence_ms: int = field(default=0, init=False)

    @property
    def heard_speech(self) -> bool:
        return self.speech_ms >= self.min_speech_ms

    def feed(self, probability: float) -> Endpoint:
        self.elapsed_ms += self.frame_ms
        if probability >= self.threshold:
            self.speech_ms += self.frame_ms
            self.silence_ms = 0
        else:
            self.silence_ms += self.frame_ms

        if self.heard_speech and self.silence_ms >= self.end_silence_ms:
            return Endpoint.DONE
        if self.elapsed_ms >= self.max_ms:
            return Endpoint.TOO_LONG if self.heard_speech else Endpoint.NO_SPEECH
        if not self.heard_speech and self.elapsed_ms >= self.no_speech_ms:
            return Endpoint.NO_SPEECH
        return Endpoint.CONTINUE
