"""Check the voice pipeline without speaking: synthesized speech goes through the real models.

Windows SAPI says "Hey Jarvis ... <command>" into a WAV file. Then the real openWakeWord model,
Silero VAD endpointing, and Whisper process it frame by frame, exactly like microphone audio.

Usage:
    uv run python scripts/voice_selftest.py
    uv run python scripts/voice_selftest.py --command "search the web for the weather"
    uv run python scripts/voice_selftest.py --agent     # also run the command and speak the reply
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

from jarvis.config import load_settings
from jarvis.voice.audio import FRAME_MS, FRAME_SAMPLES, SAMPLE_RATE
from jarvis.voice.endpoint import Endpoint, Endpointer
from jarvis.voice.stt import Transcriber
from jarvis.voice.wake import SileroVAD, WakeWordDetector

_SAPI_TO_WAV = (
    "Add-Type -AssemblyName System.Speech; "
    "$s = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
    "$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo("
    "16000, [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen, "
    "[System.Speech.AudioFormat.AudioChannel]::Mono); "
    "$s.SetOutputToWaveFile('{path}', $fmt); "
    "$s.Speak([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{text}'))); "
    "$s.Dispose()"
)


def sapi_speech(text: str) -> np.ndarray:
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "speech.wav"
        payload = base64.b64encode(text.encode("utf-8")).decode("ascii")
        script = _SAPI_TO_WAV.format(path=str(path).replace("'", "''"), text=payload)
        subprocess.run(
            ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
            check=True,
            capture_output=True,
        )
        with wave.open(str(path), "rb") as wav:
            audio = np.frombuffer(wav.readframes(wav.getnframes()), dtype=np.int16)
    loud = np.flatnonzero(np.abs(audio) > 300)  # trim SAPI's own leading and trailing silence
    return audio[loud[0] : loud[-1] + 1] if loud.size else audio


def silence(seconds: float, noise: int = 30) -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(-noise, noise, int(SAMPLE_RATE * seconds)).astype(np.int16)


def frames_of(audio: np.ndarray) -> list[np.ndarray]:
    usable = len(audio) - len(audio) % FRAME_SAMPLES
    return [audio[i : i + FRAME_SAMPLES] for i in range(0, usable, FRAME_SAMPLES)]


async def run_agent(text: str) -> None:
    from rich.console import Console

    from jarvis.app import build_app
    from jarvis.console import ConsoleChannel, ConsoleRenderer

    console = Console()
    settings = load_settings()
    app = build_app(settings, ConsoleChannel(console))
    app.bus.subscribe(ConsoleRenderer(console))
    result = await app.agent.run_turn(text, source="voice")
    await app.services.tts.speak(result.text)
    await app.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command", default="Open notepad.")
    parser.add_argument("--agent", action="store_true", help="run the command for real")
    args = parser.parse_args()

    settings = load_settings()
    cfg = settings.voice
    wake_audio = sapi_speech("Hey Jarvis.")
    command_audio = sapi_speech(args.command)
    audio = np.concatenate([silence(1.0), wake_audio, silence(0.5), command_audio, silence(2.0)])
    command_end_ms = int(
        (1.0 + 0.5) * 1000 + (len(wake_audio) + len(command_audio)) * 1000 / SAMPLE_RATE
    )
    wake_end_ms = int(1000 + len(wake_audio) * 1000 / SAMPLE_RATE)
    frames = frames_of(audio)

    started = time.perf_counter()
    wake = WakeWordDetector(cfg.wake_word, settings.models_dir)
    vad = SileroVAD(settings.models_dir, cfg.wake_word)
    stt = Transcriber(cfg, settings.models_dir)
    wake.load()
    vad.load()
    stt.load()
    print(f"models loaded in {time.perf_counter() - started:.1f}s")

    best, detected_at = 0.0, None
    for index, frame in enumerate(frames):
        score = wake.score(frame)
        best = max(best, score)
        if score >= cfg.wake_threshold:
            detected_at = index
            break
    if detected_at is None:
        print(
            f"FAIL wake word not detected (best score {best:.2f}, threshold {cfg.wake_threshold})"
        )
        return
    detect_ms = (detected_at + 1) * FRAME_MS
    delay = detect_ms - wake_end_ms
    print(f"ok   wake word detected {delay:+d} ms after it was said (score {best:.2f})")

    endpointer = Endpointer(
        frame_ms=FRAME_MS,
        threshold=cfg.vad_threshold,
        end_silence_ms=cfg.end_silence_ms,
        max_ms=int(cfg.max_utterance_s * 1000),
        no_speech_ms=int(cfg.no_speech_timeout_s * 1000),
    )
    captured: list[np.ndarray] = []
    verdict = Endpoint.CONTINUE
    end_index = detected_at
    for end_index in range(detected_at + 1, len(frames)):
        captured.append(frames[end_index])
        verdict = endpointer.feed(vad.probability(frames[end_index]))
        if verdict is not Endpoint.CONTINUE:
            break
    end_ms = (end_index + 1) * FRAME_MS
    mark = "ok  " if verdict is Endpoint.DONE else "FAIL"
    print(f"{mark} end of speech ({verdict}) noticed {end_ms - command_end_ms:+d} ms after it")

    transcript = stt.transcribe(np.concatenate(captured))
    print(f"ok   heard {transcript.text!r} in {transcript.stt_ms} ms")
    print(f"     you stop talking -> text ready: {end_ms - command_end_ms + transcript.stt_ms} ms")

    if args.agent and transcript.text:
        asyncio.run(run_agent(transcript.text))


if __name__ == "__main__":
    main()
