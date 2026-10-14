"""Where voice models live and how they get downloaded (into %LOCALAPPDATA%\\Jarvis\\models)."""

from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger(__name__)


def whisper_dir(models_dir: Path) -> Path:
    return models_dir / "whisper"


def piper_voice_path(models_dir: Path, voice: str) -> Path:
    return models_dir / "piper" / f"{voice}.onnx"


def wake_dir(models_dir: Path) -> Path:
    return models_dir / "openwakeword"


def ensure_piper_voice(models_dir: Path, voice: str) -> Path:
    path = piper_voice_path(models_dir, voice)
    if not path.exists() or not path.with_suffix(".onnx.json").exists():
        from piper.download_voices import download_voice

        log.info("Downloading Piper voice %s", voice)
        path.parent.mkdir(parents=True, exist_ok=True)
        download_voice(voice, path.parent)
    return path


def ensure_wake_models(models_dir: Path, wake_word: str) -> dict[str, Path]:
    """Download the wake word, its feature models, and Silero VAD if missing."""
    folder = wake_dir(models_dir)
    if not list(folder.glob(f"{wake_word}*.onnx")) or not (folder / "silero_vad.onnx").exists():
        from openwakeword.utils import download_models

        log.info("Downloading openWakeWord models for %s", wake_word)
        folder.mkdir(parents=True, exist_ok=True)
        download_models([wake_word], target_directory=str(folder))
    matches = sorted(folder.glob(f"{wake_word}*.onnx"))
    if not matches:
        raise FileNotFoundError(f"No openWakeWord model named '{wake_word}' in {folder}")
    return {
        "wake": matches[-1],
        "melspec": folder / "melspectrogram.onnx",
        "embedding": folder / "embedding_model.onnx",
        "vad": folder / "silero_vad.onnx",
    }
