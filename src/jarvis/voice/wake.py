"""Wake word detection (openWakeWord, ONNX backend) and voice activity detection (Silero VAD).

openWakeWord's TFLite backend does not support Windows, so models are loaded as ONNX with
explicit paths under the Jarvis models folder.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from jarvis.voice.audio import Audio
from jarvis.voice.models import ensure_wake_models

log = logging.getLogger(__name__)


class WakeWordDetector:
    def __init__(self, wake_word: str, models_dir: Path) -> None:
        self._wake_word = wake_word
        self._models_dir = models_dir
        self._model: Any = None

    def load(self) -> None:
        if self._model is not None:
            return
        from openwakeword.model import Model

        paths = ensure_wake_models(self._models_dir, self._wake_word)
        self._model = Model(
            wakeword_models=[str(paths["wake"])],
            inference_framework="onnx",
            melspec_model_path=str(paths["melspec"]),
            embedding_model_path=str(paths["embedding"]),
        )

    def score(self, frame: Audio) -> float:
        """Confidence (0 to 1) that the wake word was just said. Blocking, a few milliseconds."""
        self.load()
        scores: dict[str, float] = self._model.predict(frame)
        return max(scores.values(), default=0.0)

    def reset(self) -> None:
        """Clear the model's audio buffer so one utterance does not trigger twice."""
        if self._model is not None:
            self._model.reset()


class SileroVAD:
    """Probability that a frame contains speech."""

    def __init__(self, models_dir: Path, wake_word: str) -> None:
        self._models_dir = models_dir
        self._wake_word = wake_word
        self._vad: Any = None

    def load(self) -> None:
        if self._vad is not None:
            return
        from openwakeword.vad import VAD

        paths = ensure_wake_models(self._models_dir, self._wake_word)
        self._vad = VAD(model_path=str(paths["vad"]))

    def probability(self, frame: Audio) -> float:
        self.load()
        return float(self._vad.predict(frame, frame_size=640))
