"""Pick the configured voice engine, falling back to Windows SAPI if Piper is unavailable."""

from __future__ import annotations

import logging

from jarvis.config import Settings
from jarvis.voice.tts.base import TTSEngine
from jarvis.voice.tts.sapi import SapiTTS

log = logging.getLogger(__name__)


def build_tts(settings: Settings) -> TTSEngine:
    if settings.tts.engine == "piper":
        try:
            from jarvis.voice.tts.piper_engine import PiperTTS
        except ImportError:
            log.warning(
                "Piper is not installed (uv sync --extra voice --extra piper), "
                "using the Windows SAPI voice instead."
            )
        else:
            return PiperTTS(
                settings.tts.piper_voice, settings.models_dir, speed=settings.tts.piper_speed
            )
    return SapiTTS(rate=settings.tts.rate)
