"""The wake word verifier: advice from a wake test, loading a trained verifier, and training
guards. openWakeWord is faked; no microphone or model is used."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from jarvis.voice import wake, wake_training
from jarvis.voice.runner import wake_advice
from jarvis.voice.wake import WakeWordDetector


def test_advice_for_scores_below_the_threshold() -> None:
    tip = wake_advice([0.0, 0.25, 0.44, 0.42, 0.01], 0.5, verified=False)
    assert "scored up to 0.44, 0.42, 0.25" in tip
    assert "uv run jarvis voice --train-wake" in tip
    assert "wake_threshold = 0.35" in tip  # 80% of the best near miss


def test_advice_when_it_works_or_never_registers() -> None:
    assert wake_advice([0.1, 0.93], 0.5, verified=False).startswith("It works")
    assert "check the microphone" in wake_advice([0.0, 0.02], 0.5, verified=False)
    assert "Train again" in wake_advice([0.3], 0.5, verified=True)


class FakeModel:
    made: ClassVar[list[dict[str, Any]]] = []

    def __init__(self, **options: Any) -> None:
        FakeModel.made.append(options)


@pytest.fixture
def models(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    import openwakeword.model

    FakeModel.made = []
    monkeypatch.setattr(openwakeword.model, "Model", FakeModel)
    folder = tmp_path / "openwakeword"
    folder.mkdir()
    for name in (
        "hey_jarvis_v0.1.onnx",
        "melspectrogram.onnx",
        "embedding_model.onnx",
        "silero_vad.onnx",
    ):
        (folder / name).write_bytes(b"")
    monkeypatch.setattr(wake, "ensure_wake_models", lambda d, w: _paths(folder))
    return tmp_path


def _paths(folder: Path) -> dict[str, Path]:
    return {
        "wake": folder / "hey_jarvis_v0.1.onnx",
        "melspec": folder / "melspectrogram.onnx",
        "embedding": folder / "embedding_model.onnx",
        "vad": folder / "silero_vad.onnx",
    }


def test_no_verifier_until_one_is_trained(models: Path) -> None:
    detector = WakeWordDetector("hey_jarvis", models)
    detector.load()
    assert "custom_verifier_models" not in FakeModel.made[0]
    assert not detector.verified


def test_a_trained_verifier_is_used(models: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trained = wake_training.verifier_path(models, "hey_jarvis")
    monkeypatch.setattr(wake, "verifier_path", lambda d, w: trained)
    trained.write_bytes(b"x")
    detector = WakeWordDetector("hey_jarvis", models, verifier_floor=0.15)
    detector.load()
    assert FakeModel.made[0]["custom_verifier_models"] == {"hey_jarvis_v0.1": str(trained)}
    assert FakeModel.made[0]["custom_verifier_threshold"] == 0.15
    assert detector.verified


def test_the_verifier_can_be_turned_off(models: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    trained = wake_training.verifier_path(models, "hey_jarvis")
    monkeypatch.setattr(wake, "verifier_path", lambda d, w: trained)
    trained.write_bytes(b"x")
    WakeWordDetector("hey_jarvis", models, verifier=False).load()
    assert "custom_verifier_models" not in FakeModel.made[0]


class SilentModel:
    """Never scores anything: what silence or a different phrase looks like."""

    model_inputs: ClassVar[dict[str, int]] = {"hey_jarvis_v0.1": 16}

    def predict(self, frame: Any) -> dict[str, float]:
        return {"hey_jarvis_v0.1": 0.0}

    def reset(self) -> None:
        return None


def test_training_on_silence_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(wake_training, "_model", lambda *a, **k: (SilentModel(), "hey_jarvis_v0.1"))
    silence = [np.zeros(32_000, dtype=np.int16)] * 3
    with pytest.raises(ValueError, match="registered at all"):
        wake_training.train(tmp_path, "hey_jarvis", silence, silence)
    assert not wake_training.verifier_path(tmp_path, "hey_jarvis").exists()


def test_recordings_round_trip(tmp_path: Path) -> None:
    clip = (np.arange(32_000) % 200).astype(np.int16)
    wake_training.save_wav(tmp_path / "a" / "01.wav", clip)
    (back,) = wake_training.load_wavs(tmp_path / "a")
    assert np.array_equal(back, clip)
    assert [len(c) for c in wake_training.split(np.zeros(50_000, dtype=np.int16))] == [32_000]
