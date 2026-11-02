from __future__ import annotations

import asyncio
import sys
from collections.abc import Sequence

import numpy as np
import pytest

from jarvis.core.channel import ConfirmationRequest, FirstAnswerChannel
from jarvis.platform.hotkeys import parse_hotkey
from jarvis.voice.audio import rms, tone
from jarvis.voice.channel import match_option
from jarvis.voice.endpoint import Endpoint, Endpointer
from jarvis.voice.phrases import clean_transcript, is_stop_command, parse_yes
from jarvis.voice.tts.piper_engine import split_sentences


def test_parse_hotkey() -> None:
    hotkey = parse_hotkey("Ctrl+Alt+Space")
    assert (hotkey.modifiers, hotkey.vk) == (0x0002 | 0x0001, 0x20)
    assert parse_hotkey("f9").vk == 0x78
    assert parse_hotkey("ctrl+shift+j").vk == ord("J")
    for bad in ("ctrl+alt", "ctrl+a+b", "ctrl+banana"):
        with pytest.raises(ValueError, match="key"):
            parse_hotkey(bad)


@pytest.mark.parametrize(
    ("text", "expected"),
    [("Stop.", True), ("Jarvis, stop!", True), ("never mind", True), ("stop the music", False)],
)
def test_stop_commands(text: str, expected: bool) -> None:
    assert is_stop_command(text) is expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Yes.", True),
        ("Yes, send it.", True),
        ("go ahead please", True),
        ("yes but wait", False),
        ("No.", False),
        ("", False),
        ("maybe", False),
    ],
)
def test_only_clear_yes_confirms(text: str, expected: bool) -> None:
    assert parse_yes(text) is expected


def test_clean_transcript() -> None:
    assert clean_transcript(" Thank you. ") == ""
    assert clean_transcript("Hey Jarvis, open notepad.") == "open notepad."
    assert clean_transcript("Jarvis what time is it") == "what time is it"


def test_endpointer_detects_end_of_speech() -> None:
    ep = Endpointer(frame_ms=80, end_silence_ms=400, no_speech_ms=2000, max_ms=5000)
    results = [ep.feed(p) for p in [0.9, 0.9, 0.9, 0.1, 0.1, 0.1, 0.1, 0.1]]
    assert results[-1] is Endpoint.DONE
    assert Endpoint.DONE not in results[:-1]


def test_endpointer_timeouts() -> None:
    quiet = Endpointer(frame_ms=100, no_speech_ms=500)
    assert [quiet.feed(0.0) for _ in range(5)][-1] is Endpoint.NO_SPEECH
    talker = Endpointer(frame_ms=100, max_ms=500)
    assert [talker.feed(0.9) for _ in range(5)][-1] is Endpoint.TOO_LONG


def test_split_sentences_merges_short_pieces() -> None:
    assert split_sentences("Hi. I opened Notepad for you. It is ready!") == [
        "Hi. I opened Notepad for you.",
        "It is ready!",
    ]
    assert split_sentences("   ") == []


def test_match_option() -> None:
    options = ["Spotify", "Notepad", "Visual Studio Code"]
    assert match_option("the second one", options) == "Notepad"
    assert match_option("Spotify please", options) == "Spotify"
    assert match_option("something else", options) == "something else"


def test_tone_and_rms() -> None:
    beep = tone(440, 100, rate=16_000)
    assert beep.dtype == np.int16
    assert len(beep) == 1600
    assert rms(beep) > 1000
    assert rms(np.zeros(10, dtype=np.int16)) == 0.0


class _Channel:
    def __init__(self, name: str, delay: float, answer: bool) -> None:
        self.name = name
        self.delay = delay
        self.answer = answer
        self.cancelled = False

    async def confirm(self, request: ConfirmationRequest) -> bool:
        try:
            await asyncio.sleep(self.delay)
        except asyncio.CancelledError:
            self.cancelled = True
            raise
        return self.answer

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        await asyncio.sleep(self.delay)
        return self.name


async def test_first_answer_wins_and_others_are_cancelled() -> None:
    fast, slow = _Channel("voice", 0.01, True), _Channel("cli", 5, False)
    channel = FirstAnswerChannel(slow, fast)
    request = ConfirmationRequest("r", "open_app", "Open Paint", "d", None, 30)
    assert await channel.confirm(request) is True
    assert slow.cancelled
    assert channel.name == "voice"
    assert await channel.ask("which?") == "voice"


def test_tts_falls_back_to_sapi_without_piper(
    monkeypatch: pytest.MonkeyPatch, settings: object
) -> None:
    from jarvis.voice.tts.factory import build_tts
    from jarvis.voice.tts.sapi import SapiTTS

    monkeypatch.setitem(sys.modules, "jarvis.voice.tts.piper_engine", None)
    assert isinstance(build_tts(settings), SapiTTS)  # type: ignore[arg-type]


class _Broken:
    name = "voice"

    async def confirm(self, request: ConfirmationRequest) -> bool:
        raise RuntimeError("no microphone")

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        raise RuntimeError("no microphone")


async def test_a_failing_channel_drops_out_of_the_race() -> None:
    request = ConfirmationRequest("r", "open_app", "Open Paint", "d", None, 30)
    channel = FirstAnswerChannel(_Broken(), _Channel("web", 0.01, True))
    assert await channel.confirm(request) is True
    assert channel.name == "web"
    with pytest.raises(RuntimeError, match="no microphone"):
        await FirstAnswerChannel(_Broken(), _Broken()).confirm(request)
