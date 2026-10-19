"""Voice that cannot start at login: logged, retried, and picked up by the tray later."""

from __future__ import annotations

import asyncio
import logging
import sys
import types
from typing import Any

import pytest
from rich.console import Console

from jarvis.config import VoiceSettings
from jarvis.server import serve
from jarvis.server.hub import WebHub
from jarvis.server.runtime import Runtime
from jarvis.voice.stt import Transcriber
from tests.conftest import MakeApp


class FakeSession:
    state = "idle"

    def __init__(self) -> None:
        self.ran = asyncio.Event()
        self.closed = False

    async def run(self) -> None:
        self.ran.set()
        await asyncio.Event().wait()

    async def close(self) -> None:
        self.closed = True

    async def set_muted(self, muted: bool) -> None:
        return None


class FakeTray:
    def __init__(self) -> None:
        self.states: list[str] = []
        self.attached: Any = None

    def show(self, state: str) -> None:
        self.states.append(state)

    def attach_voice(self, set_muted: Any) -> None:
        self.attached = set_muted


async def test_voice_is_retried_until_it_starts(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    h = make_app()
    runtime = Runtime(h.app, WebHub())
    session = FakeSession()
    attempts: list[int] = []

    async def start_voice(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
        attempts.append(1)
        if len(attempts) < 3:
            return None, None  # the microphone is not there yet
        return session, None

    monkeypatch.setattr(serve, "_start_voice", start_voice)
    monkeypatch.setattr(serve, "VOICE_RETRY_S", (0.01,))
    monkeypatch.setattr("jarvis.voice.audio.refresh_devices", lambda: None)
    voice = serve._Voice(runtime, Console(quiet=True), object(), wake=True)  # type: ignore[arg-type]
    tray = FakeTray()
    voice.tray = tray  # type: ignore[assignment]

    assert await voice.start() is False
    with caplog.at_level(logging.INFO):
        await asyncio.wait_for(voice.keep_trying(), timeout=3)
    await asyncio.wait_for(session.ran.wait(), timeout=1)

    assert len(attempts) == 3
    assert runtime.voice is session
    assert tray.attached == session.set_muted
    assert tray.states[0] == "voice_retry"
    assert tray.states[-1] == "idle"
    assert "Voice started after 2 retries" in caplog.text
    await voice.close()
    assert session.closed


async def test_a_voice_failure_is_logged(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    # Started at login through pythonw there is no console, so the log is the only witness.
    from jarvis.voice import runner

    def create_session(*args: Any, **kwargs: Any) -> Any:
        return object()

    async def prepare(*args: Any) -> None:
        raise ValueError("No microphone matches 'Microphone Array'")

    monkeypatch.setattr(runner, "create_session", create_session)
    monkeypatch.setattr(runner, "prepare", prepare)
    h = make_app()
    with caplog.at_level(logging.WARNING):
        result = await serve._start_voice(
            h.app,
            Console(quiet=True),
            object(),
            wake=True,  # type: ignore[arg-type]
        )
    assert result == (None, None)
    assert "Voice could not start: No microphone matches" in caplog.text


def test_whisper_loads_the_downloaded_copy_without_the_network(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Any
) -> None:
    calls: list[dict[str, Any]] = []

    class FakeWhisper:
        def __init__(self, name: str, **options: Any) -> None:
            calls.append(options)
            if options.get("local_files_only") and len(calls) == 1 and name == "missing":
                raise FileNotFoundError(name)

    monkeypatch.setitem(
        sys.modules, "faster_whisper", types.SimpleNamespace(WhisperModel=FakeWhisper)
    )
    Transcriber(VoiceSettings(), tmp_path).load()
    assert calls == [calls[0]]
    assert calls[0]["local_files_only"] is True

    calls.clear()
    Transcriber(VoiceSettings(stt_model="missing"), tmp_path).load()
    assert [c.get("local_files_only", False) for c in calls] == [True, False]  # then downloads


async def test_a_crashed_voice_loop_is_started_again(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    class CrashingSession(FakeSession):
        async def run(self) -> None:
            raise ValueError("No microphone matches 'Microphone Array'")

    sessions: list[FakeSession] = [CrashingSession(), FakeSession()]

    async def start_voice(*args: Any, **kwargs: Any) -> tuple[Any, Any]:
        return sessions.pop(0), None

    monkeypatch.setattr(serve, "_start_voice", start_voice)
    monkeypatch.setattr(serve, "VOICE_RETRY_S", (0.01,))
    monkeypatch.setattr("jarvis.voice.audio.refresh_devices", lambda: None)
    h = make_app()
    runtime = Runtime(h.app, WebHub())
    voice = serve._Voice(runtime, Console(quiet=True), object(), wake=True)  # type: ignore[arg-type]
    assert await voice.start() is True
    async with asyncio.timeout(3):
        while sessions or runtime.voice is None:  # noqa: ASYNC110
            await asyncio.sleep(0.01)
    assert isinstance(runtime.voice, FakeSession)
    assert not isinstance(runtime.voice, CrashingSession)
    await voice.close()


async def test_a_missing_microphone_fails_before_models_load(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    from jarvis.voice import runner

    loaded: list[str] = []

    class Session:
        async def load(self) -> None:
            loaded.append("models")

    def missing(spec: Any) -> Any:
        raise ValueError(f"No microphone matches '{spec}'")

    monkeypatch.setattr(runner, "resolve_input_device", missing)
    h = make_app(overrides={"voice": {"input_device": "Nope"}})
    with pytest.raises(ValueError, match="Nope"):
        await runner.prepare(Session(), h.app.settings, Console(quiet=True))  # type: ignore[arg-type]
    assert loaded == []
