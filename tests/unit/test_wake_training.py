"""The wake word verifier: advice from a wake test, loading a trained verifier, and training
guards. openWakeWord is faked; no microphone or model is used."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import numpy as np
import pytest

from jarvis.voice import wake, wake_training
from jarvis.voice.runner import count_tries, wake_advice
from jarvis.voice.wake import WakeWordDetector

# Half-second lines like the first real tests: speech, then the score in the pause after it.
LOUD, PAUSE = 1500.0, 10.0


def test_advice_for_scores_below_the_threshold() -> None:
    peaks = [0.0, 0.25, 0.0, 0.44, 0.0, 0.42, 0.01]
    loudness = [LOUD, PAUSE, LOUD, PAUSE, LOUD, PAUSE, PAUSE]
    tip = wake_advice(peaks, loudness, 0.5, verified=False)
    assert tip.startswith("Caught 0 of about 3 tries.")
    assert "scored 0.44, 0.42, 0.25" in tip
    assert "uv run jarvis voice --train-wake" in tip
    assert "wake_threshold = 0.35" in tip  # 80% of the best near miss


def test_two_of_many_is_not_called_working() -> None:
    peaks = [0.0, 0.96] + [0.0, 0.45] * 6 + [0.0, 0.7]
    loudness = [LOUD, PAUSE] * 8
    tip = wake_advice(peaks, loudness, 0.5, verified=False)
    assert tip.startswith("Caught 2 of about 8 tries.")
    assert "--train-wake" in tip


def test_advice_when_it_works_or_never_registers() -> None:
    working = wake_advice([0.0, 0.93, 0.0, 0.9], [LOUD, PAUSE, LOUD, PAUSE], 0.5, verified=False)
    assert working.startswith("Caught 2 of about 2 tries. It works.")
    assert "check the microphone" in wake_advice([0.0, 0.02], [LOUD, PAUSE], 0.5, verified=False)
    assert "Train again" in wake_advice([0.0, 0.3], [LOUD, PAUSE], 0.5, verified=True)


def test_counting_tries() -> None:
    assert count_tries([PAUSE, LOUD, LOUD, PAUSE, LOUD, 200.0, LOUD, PAUSE]) == 2


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
