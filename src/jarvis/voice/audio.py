"""Microphone input and speaker output.

Input is 16 kHz mono int16 in 80 ms frames (1280 samples), the frame size openWakeWord expects.
sounddevice delivers frames on its own thread; they are handed to asyncio thread-safely.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from typing import Any

import numpy as np
import numpy.typing as npt

log = logging.getLogger(__name__)

SAMPLE_RATE = 16_000
FRAME_SAMPLES = 1280  # 80 ms
FRAME_MS = FRAME_SAMPLES * 1000 // SAMPLE_RATE

Audio = npt.NDArray[np.int16]


class MicStream:
    """The microphone as an async source of frames. Open only while Jarvis needs it."""

    def __init__(self, device: str | int | None = None, max_queued_frames: int = 250) -> None:
        self._device = device
        self._queue: asyncio.Queue[Audio | None] = asyncio.Queue(maxsize=max_queued_frames)
        self._stream: Any = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def active(self) -> bool:
        return self._stream is not None

    async def start(self) -> None:
        if self._stream is not None:
            return
        import sounddevice as sd

        self._loop = asyncio.get_running_loop()
        self.drain()
        stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=FRAME_SAMPLES,
            device=resolve_input_device(self._device),
            callback=self._on_audio,
        )
        stream.start()
        self._stream = stream

    async def stop(self) -> None:
        stream, self._stream = self._stream, None
        if stream is not None:
            await asyncio.to_thread(_close_stream, stream)
        self._put(None)  # wakes up any reader so it can exit

    async def restart(self) -> None:
        """Reopen a stream that stopped sending audio (sleep and resume, a device change).

        PortAudio lists devices once, so the list is refreshed first: a microphone that came
        back under a new index, or appeared after login, is found again.
        """
        stream, self._stream = self._stream, None
        if stream is not None:
            await asyncio.to_thread(_close_stream, stream)
        await asyncio.to_thread(refresh_devices)
        await self.start()

    async def read(self) -> Audio | None:
        """The next frame, or None once the stream has stopped."""
        return await self._queue.get()

    def drain(self) -> None:
        while not self._queue.empty():
            self._queue.get_nowait()

    def _on_audio(self, indata: Any, frames: int, time_info: Any, status: Any) -> None:
        if status:
            log.debug("Microphone status: %s", status)
        frame = np.asarray(indata[:, 0], dtype=np.int16).copy()
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._put, frame)

    def _put(self, frame: Audio | None) -> None:
        if self._queue.full():
            self._queue.get_nowait()  # drop the oldest frame rather than block the audio thread
        self._queue.put_nowait(frame)


def _close_stream(stream: Any) -> None:
    with contextlib.suppress(Exception):
        stream.stop()
    with contextlib.suppress(Exception):
        stream.close()


class AudioPlayer:
    """Plays int16 audio in small blocks so it can be stopped almost instantly."""

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._lock = threading.Lock()

    def play(self, samples: Audio, sample_rate: int) -> bool:
        """Blocking. Returns False if playback was stopped early."""
        import sounddevice as sd

        block = max(1, sample_rate // 20)  # 50 ms
        with self._lock:
            self._stop.clear()
            with sd.OutputStream(samplerate=sample_rate, channels=1, dtype="int16") as out:
                for start in range(0, len(samples), block):
                    if self._stop.is_set():
                        out.abort()
                        return False
                    out.write(samples[start : start + block])
        return True

    def stop(self) -> None:
        self._stop.set()


def tone(freq_hz: float, ms: int, *, volume: float = 0.2, rate: int = 22_050) -> Audio:
    """A short sine tone with soft edges, used for listening cues."""
    count = int(rate * ms / 1000)
    t = np.arange(count) / rate
    wave = np.sin(2 * np.pi * freq_hz * t) * volume
    fade = min(count // 4, int(rate * 0.01))
    if fade:
        ramp = np.linspace(0.0, 1.0, fade)
        wave[:fade] *= ramp
        wave[-fade:] *= ramp[::-1]
    return (wave * 32767).astype(np.int16)


class Earcons:
    """Tiny sounds that tell you Jarvis started or stopped listening."""

    RATE = 22_050

    def __init__(self, player: AudioPlayer, enabled: bool = True) -> None:
        self._player = player
        self._enabled = enabled
        self._listen = np.concatenate([tone(660, 70), tone(880, 90)])
        self._done = np.concatenate([tone(880, 60), tone(587, 90)])

    async def listening(self) -> None:
        await self._play(self._listen)

    async def cancelled(self) -> None:
        await self._play(self._done)

    async def _play(self, samples: Audio) -> None:
        if self._enabled:
            try:
                await asyncio.to_thread(self._player.play, samples, self.RATE)
            except Exception:
                log.debug("Earcon playback failed", exc_info=True)


SILENT_RMS = 2.0  # a real microphone always picks up some noise; this is digital silence


async def microphone_level(device: str | int | None, seconds: float = 0.6) -> float:
    """Open the microphone briefly and return its loudness (RMS), for a startup check."""
    mic = MicStream(device)
    await mic.start()
    try:
        frames: list[Audio] = []
        for _ in range(max(2, int(seconds * 1000 / FRAME_MS))):
            frame = await asyncio.wait_for(mic.read(), timeout=2)
            if frame is not None:
                frames.append(frame)
    finally:
        await mic.stop()
    return rms(np.concatenate(frames[1:] or frames)) if frames else 0.0


def rms(audio: Audio) -> float:
    if len(audio) == 0:
        return 0.0
    return float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))


PREFERRED_HOST_API = "MME"  # resamples to 16 kHz for us; WASAPI often rejects that rate


def refresh_devices() -> None:
    """Make PortAudio list the audio devices again (it caches them when first loaded).

    Only call this with no stream open: it closes PortAudio, and with it every stream.
    """
    import sounddevice as sd

    sd._terminate()
    sd._initialize()


def list_input_devices() -> list[tuple[int, str, bool]]:
    """(index, name, is_default) for microphones, one entry per device (MME host API)."""
    import sounddevice as sd

    apis = sd.query_hostapis()
    default_input = sd.default.device[0]
    return [
        (index, str(device["name"]), index == default_input)
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0
        and apis[device["hostapi"]]["name"] == PREFERRED_HOST_API
    ]


def resolve_input_device(spec: str | int | None) -> int | None:
    """Turn a config value (index, part of a name, or None for the default) into a device index.

    Every microphone appears once per Windows audio API, so a plain name is ambiguous for
    sounddevice. Prefer the MME entry, which accepts 16 kHz directly.
    """
    if spec is None or isinstance(spec, int):
        return spec
    import sounddevice as sd

    apis = sd.query_hostapis()
    wanted = spec.casefold()
    matches = [
        (apis[device["hostapi"]]["name"] != PREFERRED_HOST_API, index)
        for index, device in enumerate(sd.query_devices())
        if device["max_input_channels"] > 0 and wanted in str(device["name"]).casefold()
    ]
    if not matches:
        raise ValueError(f"No microphone matches '{spec}'. Run: uv run jarvis voice --list-devices")
    return min(matches)[1]
