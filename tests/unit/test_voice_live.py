"""Words and loudness while you speak: shown on the overlay and the page, never acted on."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.core.events import Event, TranscriptPartial, VoiceLevel
from jarvis.voice import session as session_module
from jarvis.voice.session import VoiceState
from jarvis.voice.stt import Transcript
from tests.conftest import MakeApp, reply
from tests.unit.test_voice_session import FakeDictation, FakeSTT, make_session, push_to_talk, until


class GrowingSTT(FakeSTT):
    """Hears more each time, like Whisper on a growing recording."""

    def __init__(self, *words: str) -> None:
        super().__init__()
        self.words = words

    def transcribe(self, audio: Any, *, dictation: bool = False) -> Transcript:
        self.calls += 1
        self.dictation.append(dictation)
        text = " ".join(self.words[: self.calls])
        return Transcript(text, audio_ms=len(audio) // 16, stt_ms=5)


@pytest.fixture(autouse=True)
def immediate(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(session_module, "PARTIAL_FIRST_S", 0.0)
    monkeypatch.setattr(session_module, "PARTIAL_EVERY_S", 0.0)


def recorded(bus: Any) -> list[Event]:
    events: list[Event] = []
    bus.subscribe(events.append)
    return events


async def test_partials_are_published_and_only_the_final_text_runs(make_app: MakeApp) -> None:
    h = make_app([reply("Done.")])
    events = recorded(h.app.bus)
    session, mic, _, tts = make_session(h, GrowingSTT("open", "notepad", "now"))

    await push_to_talk(session, mic, frames=4)
    await until(lambda: tts.spoken == ["Done."])
    await until(lambda: session.state is VoiceState.IDLE)

    assert any(isinstance(event, TranscriptPartial) for event in events)
    (row,) = h.app.history.recent()
    partials = [event.text for event in events if isinstance(event, TranscriptPartial)]
    assert row["input_text"] not in partials  # the command is the later, final transcript
    assert len(h.llm.requests) == 1


async def test_a_partial_stop_word_stops_nothing(make_app: MakeApp) -> None:
    """Only the final transcript is matched for "stop": a partial is never a command."""
    h = make_app([reply("Done.")])
    session, mic, cues, tts = make_session(h, GrowingSTT("stop", "the", "music"))

    await push_to_talk(session, mic, frames=4)
    await until(lambda: tts.spoken == ["Done."])
    assert cues.cancel == 0


async def test_dictation_is_never_transcribed_live(make_app: MakeApp) -> None:
    h = make_app()
    events = recorded(h.app.bus)
    typed = FakeDictation()
    stt = FakeSTT("my private note")
    session, mic, _, _ = make_session(h, stt, dictation=typed)

    session.on_hotkey("dictate", "down")
    await until(lambda: session.state is VoiceState.LISTENING)
    mic.push(6)
    session.on_hotkey("dictate", "up")
    await until(lambda: typed.inserted != [])

    assert stt.calls == 1
    assert not any(isinstance(event, TranscriptPartial) for event in events)


async def test_the_setting_turns_live_transcripts_off(make_app: MakeApp) -> None:
    h = make_app([reply("Done.")])
    h.app.settings.voice.live_transcript = False
    events = recorded(h.app.bus)
    stt = FakeSTT("open notepad")
    session, mic, _, tts = make_session(h, stt)

    await push_to_talk(session, mic, frames=6)
    await until(lambda: tts.spoken == ["Done."])

    assert stt.calls == 1
    assert not any(isinstance(event, TranscriptPartial) for event in events)


async def test_a_partial_from_an_old_recording_is_dropped(make_app: MakeApp) -> None:
    h = make_app()
    events = recorded(h.app.bus)
    session, _, _, _ = make_session(h, GrowingSTT("late"))

    await session._transcribe_live(session_module.np.zeros(1600, dtype="int16"), capture_id=99)

    assert events == []


async def test_loudness_is_published_while_recording_and_not_at_rest(make_app: MakeApp) -> None:
    h = make_app([reply("Done.")])
    events = recorded(h.app.bus)
    session, mic, _, tts = make_session(h, GrowingSTT("open", "notepad"))

    await push_to_talk(session, mic, frames=3)
    await until(lambda: tts.spoken == ["Done."])

    levels = [event.level for event in events if isinstance(event, VoiceLevel)]
    assert levels
    assert all(0.0 <= level <= 1.0 for level in levels)
