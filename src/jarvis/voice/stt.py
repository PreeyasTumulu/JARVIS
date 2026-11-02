"""Speech to text with faster-whisper. Runs on the CPU by default to leave the GPU for the LLM.

`stt_device = "cuda"` needs the `gpu` extra (cuBLAS and cuDNN as pip packages, ADR-062).
"""

from __future__ import annotations

import logging
import os
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


def add_cuda_libraries() -> bool:
    """Let CTranslate2 find cuBLAS and cuDNN from pip's NVIDIA packages, which keep their DLLs in
    site-packages/nvidia/*/bin where Windows does not look. False when they are not installed."""
    try:
        import nvidia  # the namespace package of nvidia-cublas-cu12 and nvidia-cudnn-cu12
    except ImportError:
        return False
    found = False
    for base in getattr(nvidia, "__path__", []):
        for folder in sorted(Path(base).glob("*/bin")):
            found = True
            os.environ["PATH"] = f"{folder}{os.pathsep}{os.environ.get('PATH', '')}"
            if hasattr(os, "add_dll_directory"):
                os.add_dll_directory(str(folder))
    return found


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
        self.device = "cpu"  # where the model ended up after load()
        self._model_device = "cpu"

    def load(self) -> None:
        """Load (and on first use download) the Whisper model. Blocking; call from a thread.

        "auto" uses the GPU when the `gpu` extra is installed and CUDA works, else the CPU; "cuda"
        insists on trying the GPU. Either way a GPU that fails (a missing DLL only shows up on the
        first transcription) means the CPU, never no speech at all.
        """
        with self._lock:
            if self._model is not None:
                return
            device = self._cfg.stt_device
            if device != "cpu" and not add_cuda_libraries():
                if device == "cuda":
                    log.warning("Whisper on the GPU needs: uv sync --extra gpu; using the CPU")
                device = "cpu"
            if device != "cpu":
                try:
                    self._model = self._open(device)
                    # Segments are lazy: only consuming them runs the GPU (and loads cuBLAS).
                    warm = np.zeros(SAMPLE_RATE, dtype=np.float32)
                    list(self._model.transcribe(warm, beam_size=1, language="en")[0])
                except Exception as exc:
                    log.warning("Whisper could not run on the GPU (%s); using the CPU", exc)
                    self._model = None
            if self._model is None:
                self._model = self._open("cpu")
            self.device = "cpu" if device == "cpu" or self._model_device == "cpu" else "cuda"

    def _open(self, device: str) -> Any:
        from faster_whisper import WhisperModel

        started = time.perf_counter()
        compute = self._cfg.stt_compute_type
        if device != "cpu" and compute == "int8":
            compute = "int8_float16"  # int8 weights, float16 maths: the fast GPU setting
        options: dict[str, Any] = {
            "device": "cuda" if device != "cpu" else "cpu",
            "compute_type": compute,
            "cpu_threads": self._cfg.stt_cpu_threads,
            "download_root": str(whisper_dir(self._models_dir)),
        }
        try:
            # The downloaded copy first: at login the network may not be up yet, and asking
            # Hugging Face for updates on every start only adds delay.
            model = WhisperModel(self._cfg.stt_model, local_files_only=True, **options)
        except Exception:
            log.info("Whisper %s is not downloaded yet; fetching it", self._cfg.stt_model)
            model = WhisperModel(self._cfg.stt_model, **options)
        self._model_device = options["device"]
        log.info(
            "Whisper %s loaded on the %s in %.1fs",
            self._cfg.stt_model,
            "GPU" if options["device"] == "cuda" else "CPU",
            time.perf_counter() - started,
        )
        return model

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
