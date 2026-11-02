"""Whisper's device choice: the GPU when it works, the CPU otherwise. No model is loaded."""

from __future__ import annotations

from pathlib import Path
from typing import Any, ClassVar

import pytest

from jarvis.config import VoiceSettings
from jarvis.voice import stt
from jarvis.voice.stt import Transcriber


class FakeWhisper:
    opened: ClassVar[list[dict[str, Any]]] = []
    gpu_breaks = False

    def __init__(self, name: str, **options: Any) -> None:
        self.device = options["device"]
        FakeWhisper.opened.append({"name": name, **options})

    def transcribe(self, audio: Any, **options: Any) -> Any:
        if self.device == "cuda" and FakeWhisper.gpu_breaks:
            raise RuntimeError("Library cublas64_12.dll is not found or cannot be loaded")
        return iter(()), None


@pytest.fixture
def whisper(monkeypatch: pytest.MonkeyPatch) -> type[FakeWhisper]:
    import faster_whisper

    FakeWhisper.opened = []
    FakeWhisper.gpu_breaks = False
    monkeypatch.setattr(faster_whisper, "WhisperModel", FakeWhisper)
    return FakeWhisper


def load(tmp_path: Path, device: str) -> Transcriber:
    transcriber = Transcriber(VoiceSettings(stt_device=device), tmp_path)  # type: ignore[arg-type]
    transcriber.load()
    return transcriber


def test_auto_uses_the_gpu_when_cuda_works(
    whisper: type[FakeWhisper], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt, "add_cuda_libraries", lambda: True)
    assert load(tmp_path, "auto").device == "cuda"
    assert whisper.opened[0]["compute_type"] == "int8_float16"


def test_auto_stays_on_the_cpu_without_the_gpu_extra(
    whisper: type[FakeWhisper], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt, "add_cuda_libraries", lambda: False)
    assert load(tmp_path, "auto").device == "cpu"
    assert [o["device"] for o in whisper.opened] == ["cpu"]
    assert whisper.opened[0]["compute_type"] == "int8"


def test_a_broken_gpu_falls_back_to_the_cpu(
    whisper: type[FakeWhisper], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt, "add_cuda_libraries", lambda: True)
    whisper.gpu_breaks = True  # the DLL error only shows on the first transcription
    assert load(tmp_path, "cuda").device == "cpu"
    assert [o["device"] for o in whisper.opened] == ["cuda", "cpu"]


def test_cpu_is_never_tried_on_the_gpu(
    whisper: type[FakeWhisper], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(stt, "add_cuda_libraries", lambda: pytest.fail("not on the CPU"))
    assert load(tmp_path, "cpu").device == "cpu"
