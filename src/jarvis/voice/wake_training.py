"""Teach "Hey Jarvis" your voice: a custom verifier trained on a few of your own clips (ADR-064).

openWakeWord's "hey jarvis" model was trained mostly on synthetic voices, and a real voice
with an accent can score 0.25 to 0.45 against the default threshold of 0.5. openWakeWord's
answer is a custom verifier: a small logistic regression over the model's own audio features,
trained on clips of one person saying the wake word and saying other things. When the main
model scores above a low floor, the verifier's probability replaces its score.

openWakeWord's own training helper only learns from moments the main model already scores
0.5 or more, which is exactly what a voice that needs a verifier never reaches, so positives
here are taken from 0.05 up. The clips and the verifier stay in your data folder.
"""

from __future__ import annotations

import pickle
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from jarvis.voice.audio import SAMPLE_RATE
from jarvis.voice.models import ensure_wake_models, wake_dir

STEP = 1280  # openWakeWord's 80 ms frame
POSITIVE_FLOOR = 0.05  # positive features are taken where the main model scores this much
NEGATIVE_PASSAGE = (
    "The weather in Hyderabad has been warm this week, so I keep the windows open in the "
    "evening. Tomorrow I need to finish the report, call the bank, and buy vegetables on the "
    "way home. Could you remind me to drink water? I think the meeting moved to five o'clock."
)


def verifier_path(models_dir: Path, wake_word: str) -> Path:
    return wake_dir(models_dir) / f"{wake_word}-verifier.pkl"


def training_dir(data_dir: Path) -> Path:
    return data_dir / "wake-training"


def save_wav(path: Path, audio: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(SAMPLE_RATE)
        out.writeframes(audio.astype(np.int16).tobytes())


def load_wavs(folder: Path) -> list[np.ndarray]:
    clips = []
    for path in sorted(folder.glob("*.wav")):
        with wave.open(str(path), "rb") as clip:
            clips.append(np.frombuffer(clip.readframes(clip.getnframes()), dtype=np.int16))
    return clips


def split(audio: np.ndarray, seconds: float = 2.0) -> list[np.ndarray]:
    size = int(seconds * SAMPLE_RATE)
    return [audio[i : i + size] for i in range(0, len(audio) - size + 1, size)]


@dataclass(frozen=True)
class TrainingReport:
    positive_examples: int
    negative_examples: int
    positive_scores: list[float]  # the best score per positive clip, with the verifier
    negative_best: float  # the highest score any negative clip reached, with the verifier

    @property
    def caught(self) -> int:
        return sum(score >= 0.5 for score in self.positive_scores)


def _model(models_dir: Path, wake_word: str, verifier: Path | None = None) -> tuple[Any, str]:
    from openwakeword.model import Model

    paths = ensure_wake_models(models_dir, wake_word)
    name = paths["wake"].stem
    options: dict[str, Any] = {}
    if verifier is not None:
        options = {
            "custom_verifier_models": {name: str(verifier)},
            "custom_verifier_threshold": 0.1,
        }
    model = Model(
        wakeword_models=[str(paths["wake"])],
        inference_framework="onnx",
        melspec_model_path=str(paths["melspec"]),
        embedding_model_path=str(paths["embedding"]),
        **options,
    )
    return model, name


def _features(model: Any, name: str, clip: np.ndarray, floor: float, repeats: int) -> np.ndarray:
    """The model's audio features at every frame of a clip that scores at least `floor`."""
    found = []
    rng = np.random.default_rng(len(clip))
    for _ in range(repeats):
        model.reset()
        audio = clip[int(rng.integers(0, STEP)) :] if repeats > 1 else clip
        for start in range(0, len(audio) - STEP, STEP):
            if model.predict(audio[start : start + STEP])[name] >= floor:
                found.append(model.preprocessor.get_features(model.model_inputs[name]))
    if not found:
        return np.empty((0, model.model_inputs[name], 96))
    return np.vstack(found)


def best_score(model: Any, name: str, clip: np.ndarray) -> float:
    model.reset()
    padded = np.concatenate([clip, np.zeros(SAMPLE_RATE // 2, dtype=np.int16)])
    scores = [model.predict(padded[i : i + STEP])[name] for i in range(0, len(padded) - STEP, STEP)]
    return float(max(scores, default=0.0))


def train(
    models_dir: Path,
    wake_word: str,
    positives: list[np.ndarray],
    negatives: list[np.ndarray],
) -> TrainingReport:
    """Train and save the verifier, then score every clip with it. Raises ValueError when the
    clips give nothing to learn from (silence, or a different phrase)."""
    from openwakeword.custom_verifier_model import train_verifier_model

    model, name = _model(models_dir, wake_word)
    positive = [_features(model, name, clip, POSITIVE_FLOOR, repeats=5) for clip in positives]
    pos = np.vstack(positive)
    if len(pos) == 0:
        raise ValueError(
            'None of the "Hey Jarvis" recordings registered at all. Check the microphone and '
            "say the phrase clearly, close to the laptop."
        )
    neg = np.vstack([_features(model, name, clip, 0.0, repeats=1) for clip in negatives])
    if len(neg) == 0:
        raise ValueError("The other-speech recording was silent.")
    pipeline = train_verifier_model(
        np.vstack((pos, neg)), np.array([1] * len(pos) + [0] * len(neg))
    )
    path = verifier_path(models_dir, wake_word)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as out:
        pickle.dump(pipeline, out)

    checked, _ = _model(models_dir, wake_word, verifier=path)
    return TrainingReport(
        positive_examples=len(pos),
        negative_examples=len(neg),
        positive_scores=[best_score(checked, name, clip) for clip in positives],
        negative_best=max((best_score(checked, name, clip) for clip in negatives), default=0.0),
    )
