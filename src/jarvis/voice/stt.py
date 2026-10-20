"""Speech to text with faster-whisper. Runs on the CPU by default to leave the GPU for the LLM."""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.config import VoiceSettings
from jarvis.voice.audio import SAMPLE_RATE, Audio, rms
from jarvis.voice.models import whisper_dir
from jarvis.voice.phrases import clean_dictation, clean_transcript

log = logging.getLogger(__name__)

MIN_AUDIO_MS = 300
MIN_RMS = 60.0  # below this the clip is effectively silence


@dataclass(frozen=True)
class Transcript:
    text: str
    audio_ms: int
    stt_ms: int


class Transcriber:
    def __init__(self, cfg: VoiceSettings, models_dir: Path) -> None:
        self._cfg = cfg
        self._models_dir = models_dir
        self._model: Any = None
        self._lock = threading.Lock()

    def load(self) -> None:
        """Load (and on first use download) the Whisper model. Blocking; call from a thread."""
        with self._lock:
            if self._model is not None:
                return
            from faster_whisper import WhisperModel

            started = time.perf_counter()
            options: dict[str, Any] = {
                "device": self._cfg.stt_device,
                "compute_type": self._cfg.stt_compute_type,
                "cpu_threads": self._cfg.stt_cpu_threads,
                "download_root": str(whisper_dir(self._models_dir)),
            }
            try:
                # The downloaded copy first: at login the network may not be up yet, and asking
                # Hugging Face for updates on every start only adds delay.
                self._model = WhisperModel(self._cfg.stt_model, local_files_only=True, **options)
            except Exception:
                log.info("Whisper %s is not downloaded yet; fetching it", self._cfg.stt_model)
                self._model = WhisperModel(self._cfg.stt_model, **options)
            log.info(
                "Whisper %s loaded in %.1fs", self._cfg.stt_model, time.perf_counter() - started
            )

    def transcribe(self, audio: Audio, *, dictation: bool = False) -> Transcript:
        """Blocking. Returns empty text for clips that are too short or silent.

        Dictation skips the command vocabulary hint, which would pull ordinary sentences
        toward app names, and keeps phrases a command would drop ("thank you", "Jarvis").
        """
        audio_ms = len(audio) * 1000 // SAMPLE_RATE
        if audio_ms < MIN_AUDIO_MS or rms(audio) < MIN_RMS:
            return Transcript("", audio_ms, 0)
        self.load()
        started = time.perf_counter()
        segments, _info = self._model.transcribe(
            audio.astype(np.float32) / 32768.0,
            language=self._cfg.stt_language,
            beam_size=self._cfg.stt_beam_size,
            initial_prompt=None if dictation else (self._cfg.stt_hint or None),
            condition_on_previous_text=False,
            without_timestamps=True,
            vad_filter=False,  # endpointing already trimmed the clip
        )
        parts = [
            segment.text
            for segment in segments
            if not (segment.no_speech_prob > 0.6 and segment.avg_logprob < -1.0)
        ]
        text = clean_dictation(" ".join(parts)) if dictation else clean_transcript(" ".join(parts))
        return Transcript(text, audio_ms, int((time.perf_counter() - started) * 1000))
