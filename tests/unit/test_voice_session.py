"""The voice loop end to end with fake audio and models: no microphone, speakers, or Ollama."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any

import numpy as np
import pytest

from jarvis.voice.audio import FRAME_SAMPLES
from jarvis.voice.channel import VoiceChannel
from jarvis.voice.session import VoiceSession, VoiceState
from jarvis.voice.stt import Transcript
from tests.conftest import FakeTTS, Hang, Harness, MakeApp, reply


class FakeMic:
    def __init__(self) -> None:
        self.active = False
        self.queue: asyncio.Queue[Any] = asyncio.Queue()

    async def start(self) -> None:
        self.active = True

    async def stop(self) -> None:
        self.active = False
        self.queue.put_nowait(None)

    async def read(self) -> Any:
        return await self.queue.get()

    def drain(self) -> None:
        while not self.queue.empty():
            self.queue.get_nowait()

    def push(self, count: int = 1) -> None:
        for _ in range(count):
            self.queue.put_nowait(np.full(FRAME_SAMPLES, 1000, dtype=np.int16))


class FakeSTT:
    def __init__(self, *texts: str) -> None:
        self.texts = list(texts)
        self.calls = 0

    def load(self) -> None:
        return None

    def transcribe(self, audio: Any) -> Transcript:
        self.calls += 1
        text = self.texts.pop(0) if self.texts else ""
        return Transcript(text, audio_ms=len(audio) * 1000 // 16000, stt_ms=5)


class Scripted:
    """Returns scripted values per call, then a default."""

    def __init__(self, values: list[float], default: float = 0.0) -> None:
        self.values = list(values)
        self.default = default
        self.calls = 0
        self.resets = 0

    def load(self) -> None:
        return None

    def _next(self) -> float:
        self.calls += 1
        return self.values.pop(0) if self.values else self.default

    def score(self, frame: Any) -> float:
        return self._next()

    def probability(self, frame: Any) -> float:
        return self._next()

    def reset(self) -> None:
        self.resets += 1


class FakeCues:
    def __init__(self) -> None:
        self.listen = 0
        self.cancel = 0

    async def listening(self) -> None:
        self.listen += 1

    async def cancelled(self) -> None:
        self.cancel += 1


class BlockingTTS(FakeTTS):
    """Speaks until stop() is called, like a long reply being interrupted."""

    def __init__(self) -> None:
        super().__init__()
        self.stopped = asyncio.Event()

    async def speak(self, text: str) -> None:
        self.spoken.append(text)
        self.stopped.clear()
        await self.stopped.wait()

    async def stop(self) -> None:
        self.stopped.set()


async def until(condition: Callable[[], bool], limit_s: float = 3.0) -> None:
    """Poll a condition. Fine in tests, where the session exposes no event for every state."""
    async with asyncio.timeout(limit_s):
        while not condition():  # noqa: ASYNC110
            await asyncio.sleep(0.01)


def make_session(
    h: Harness,
    stt: FakeSTT,
    *,
    tts: FakeTTS | None = None,
    wake: Scripted | None = None,
    vad: Scripted | None = None,
) -> tuple[VoiceSession, FakeMic, FakeCues, FakeTTS]:
    mic, cues = FakeMic(), FakeCues()
    voice_tts = tts or h.tts
    session = VoiceSession(
        agent=h.app.agent,
        bus=h.app.bus,
        settings=h.app.settings,
        mic=mic,
        stt=stt,
        tts=voice_tts,
        cues=cues,
        wake=wake,
        vad=vad,
    )
    return session, mic, cues, voice_tts


async def push_to_talk(session: VoiceSession, mic: FakeMic, frames: int = 8) -> None:
    session.on_hotkey("ptt", "down")
    await until(lambda: session.state is VoiceState.LISTENING)
    mic.push(frames)
    session.on_hotkey("ptt", "up")


async def test_push_to_talk_runs_a_command_and_speaks(make_app: MakeApp, launched: list) -> None:
    h = make_app([reply("", ("open_app", {"name": "notepad"})), reply("Notepad is open.")])
    session, mic, cues, tts = make_session(h, FakeSTT("open notepad"))

    await push_to_talk(session, mic)
    await until(lambda: tts.spoken == ["Notepad is open."])
    await until(lambda: session.state is VoiceState.IDLE)

    assert [entry.name for entry in launched] == ["Notepad"]
    assert cues.listen == 1
    assert mic.active is False  # push-to-talk only opens the microphone while you talk
    (row,) = h.app.history.recent()
    assert row["source"] == "voice"
    timings = json.loads(row["timings_json"])
    assert {"stt_ms", "audio_ms", "pre_turn_ms", "first_tool_ms", "llm_ms"} <= timings.keys()
    assert len(session.heard_to_action_ms) == 1


async def test_stop_word_never_reaches_the_model(make_app: MakeApp) -> None:
    h = make_app()
    session, mic, cues, _ = make_session(h, FakeSTT("Stop."))
    await push_to_talk(session, mic)
    await until(lambda: cues.cancel == 1)
    assert h.llm.requests == []
    assert session.state is VoiceState.IDLE


async def test_empty_transcript_goes_back_to_idle(make_app: MakeApp) -> None:
    h = make_app()
    session, mic, cues, _ = make_session(h, FakeSTT(""))
    await push_to_talk(session, mic)
    await until(lambda: cues.cancel == 1)
    assert h.llm.requests == []


@pytest.mark.parametrize(("answer", "opened"), [("Yes, go ahead.", True), ("no", False)])
async def test_voice_confirmation(
    make_app: MakeApp, launched: list, answer: str, opened: bool
) -> None:
    channel = VoiceChannel()
    h = make_app(
        [reply("", ("open_app", {"name": "spotify"})), reply("Done.")],
        channel=channel,  # type: ignore[arg-type]
    )
    session, mic, _, tts = make_session(h, FakeSTT("open spotify", answer))
    channel.attach(session)

    await push_to_talk(session, mic)
    await until(lambda: session.state is VoiceState.AWAITING_ANSWER)
    assert tts.spoken == ["Should I open Spotify? Say yes or no."]

    await push_to_talk(session, mic)  # answering does not cancel the running command
    await until(lambda: tts.spoken[-1] == "Done.")

    assert bool(launched) is opened
    (row,) = h.audit()
    assert row["decision"] == ("confirmed" if opened else "denied")
    if opened:
        assert row["confirmed_via"] == "voice"


async def test_push_to_talk_interrupts_speech(make_app: MakeApp) -> None:
    h = make_app([reply("A very long answer.")])
    tts = BlockingTTS()
    session, mic, _, _ = make_session(h, FakeSTT("tell me a story"), tts=tts)

    await push_to_talk(session, mic)
    await until(lambda: session.state is VoiceState.SPEAKING)
    session.on_hotkey("ptt", "down")
    await until(lambda: tts.stopped.is_set())
    await until(lambda: session.state is VoiceState.LISTENING)


async def test_stop_hotkey_cancels_a_slow_command(make_app: MakeApp) -> None:
    h = make_app([Hang()])
    session, mic, _, tts = make_session(h, FakeSTT("what is the meaning of life"))

    await push_to_talk(session, mic)
    await until(lambda: h.app.agent.busy)
    session.on_hotkey("stop", "down")
    await until(lambda: bool(h.app.history.recent()))

    assert h.app.history.recent()[0]["status"] == "cancelled"
    assert tts.spoken == []
    await until(lambda: session.state is VoiceState.IDLE)


async def test_wake_word_then_endpointing(make_app: MakeApp, launched: list) -> None:
    h = make_app([reply("", ("open_app", {"name": "notepad"})), reply("Opened.")])
    wake = Scripted([0.1, 0.95])
    vad = Scripted([0.9] * 4 + [0.1] * 12)
    session, mic, _cues, tts = make_session(h, FakeSTT("open notepad"), wake=wake, vad=vad)
    runner = asyncio.create_task(session.run())
    try:
        await until(lambda: mic.active)
        mic.push(2)  # second frame scores above the threshold
        await until(lambda: session.state is VoiceState.LISTENING)
        mic.push(16)  # four frames of speech, then silence
        await until(lambda: tts.spoken == ["Opened."])
        assert [entry.name for entry in launched] == ["Notepad"]
        assert wake.resets >= 1
        assert mic.active is True  # wake word mode keeps listening
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
    assert mic.active is False


async def test_wake_word_with_no_speech_returns_to_idle(make_app: MakeApp) -> None:
    h = make_app(overrides={"voice": {"no_speech_timeout_s": 0.6}})
    stt = FakeSTT("should not be used")
    session, mic, cues, _ = make_session(
        h, stt, wake=Scripted([0.95]), vad=Scripted([], default=0.05)
    )
    runner = asyncio.create_task(session.run())
    try:
        await until(lambda: mic.active)
        mic.push(1)
        await until(lambda: session.state is VoiceState.LISTENING)
        mic.push(10)
        await until(lambda: cues.cancel == 1)
        assert stt.calls == 0
        assert session.state is VoiceState.IDLE
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_wake_word_is_ignored_while_speaking(make_app: MakeApp) -> None:
    h = make_app([reply("Talking for a while.")])
    tts = BlockingTTS()
    wake = Scripted([], default=0.99)
    session, mic, _, _ = make_session(
        h, FakeSTT("hello"), tts=tts, wake=wake, vad=Scripted([0.9] * 3 + [0.0] * 12)
    )
    runner = asyncio.create_task(session.run())
    try:
        await until(lambda: mic.active)
        mic.push(1)
        await until(lambda: session.state is VoiceState.LISTENING)
        mic.push(15)
        await until(lambda: session.state is VoiceState.SPEAKING)
        calls_before = wake.calls
        mic.push(5)
        await asyncio.sleep(0.1)
        assert wake.calls == calls_before  # our own voice cannot trigger the wake word
    finally:
        await tts.stop()
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_announcements_wait_until_jarvis_is_idle(make_app: MakeApp) -> None:
    h = make_app([Hang()])
    session, mic, _, tts = make_session(h, FakeSTT("what is the meaning of life"))
    await push_to_talk(session, mic)
    await until(lambda: session.state is VoiceState.THINKING)
    announcing = asyncio.create_task(session.announce("Reminder: stretch."))
    await asyncio.sleep(0.05)
    assert tts.spoken == []  # not while a command is running
    await session.stop()
    await until(lambda: tts.spoken == ["Reminder: stretch."])
    await announcing


class SlowNo:
    name = "web"

    async def confirm(self, request: Any) -> bool:
        await asyncio.sleep(0.05)
        return False

    async def ask(self, question: str, options: Any = None) -> str:
        await asyncio.sleep(0.05)
        return ""


async def test_a_page_answer_puts_voice_back_to_idle(make_app: MakeApp) -> None:
    from jarvis.core.channel import FirstAnswerChannel

    voice = VoiceChannel()
    h = make_app(
        [reply("", ("open_app", {"name": "spotify"})), reply("Not opened.")],
        channel=FirstAnswerChannel(voice, SlowNo()),  # type: ignore[arg-type]
    )
    session, _, _, tts = make_session(h, FakeSTT())
    voice.attach(session)
    await h.app.agent.run_turn("open spotify", source="web")  # typed in the page
    assert tts.spoken == ["Should I open Spotify? Say yes or no."]
    assert h.audit()[0]["decision"] == "denied"
    assert session.state is VoiceState.IDLE  # not stuck waiting for a spoken answer
