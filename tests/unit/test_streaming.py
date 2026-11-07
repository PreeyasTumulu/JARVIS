"""Replies spoken sentence by sentence while the model writes them (ADR-083)."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Sequence
from types import SimpleNamespace
from typing import Any

import numpy as np
import pytest

from jarvis.config import ProviderSettings
from jarvis.core.speech import SpeechStream
from jarvis.llm.client import LLMClient
from jarvis.llm.types import LLMReply
from jarvis.voice.tts.base import speak_stream
from tests.conftest import FakeLLM, FakeTTS, MakeApp, reply
from tests.unit.test_voice_session import FakeSTT, make_session, push_to_talk, until

# The model client


def _chunk(content: str | None = None, calls: list[Any] | None = None) -> Any:
    delta = SimpleNamespace(content=content, tool_calls=calls)
    return SimpleNamespace(model="m", usage=None, choices=[SimpleNamespace(delta=delta)])


def _call_part(index: int, name: str | None, arguments: str, id: str | None = None) -> Any:
    return SimpleNamespace(
        index=index, id=id, function=SimpleNamespace(name=name, arguments=arguments)
    )


class _Chunks:
    def __init__(self, chunks: Sequence[Any]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self) -> AsyncIterator[Any]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        for chunk in self._chunks:
            yield chunk


def _streaming_client(chunks: Sequence[Any]) -> tuple[LLMClient, dict[str, Any]]:
    seen: dict[str, Any] = {}

    async def create(**kwargs: Any) -> Any:
        seen.update(kwargs)
        return _Chunks(chunks)

    fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    provider = ProviderSettings(base_url="http://x/v1", model="m")
    return LLMClient(provider, client=fake), seen  # type: ignore[arg-type]


async def _stream(chunks: Sequence[Any]) -> tuple[LLMReply, list[str], dict[str, Any]]:
    client, seen = _streaming_client(chunks)
    fed: list[str] = []
    result = await client.stream([], [{"type": "function"}], on_text=fed.append)
    return result, fed, seen


async def test_text_is_handed_over_as_it_streams() -> None:
    result, fed, seen = await _stream([_chunk("It is "), _chunk("sunny. "), _chunk("Warm too.")])
    assert fed == ["It is ", "sunny. ", "Warm too."]
    assert result.text == "It is sunny. Warm too."
    assert result.tool_calls == []
    assert seen["stream"] is True


async def test_a_structured_call_is_assembled_and_nothing_is_spoken() -> None:
    result, fed, _ = await _stream(
        [
            _chunk(calls=[_call_part(0, "open_app", '{"na', id="call_9")]),
            _chunk(calls=[_call_part(0, None, 'me": "notepad"}')]),
        ]
    )
    assert fed == []
    (call,) = result.tool_calls
    assert (call.id, call.name, json.loads(call.arguments)) == (
        "call_9",
        "open_app",
        {"name": "notepad"},
    )


@pytest.mark.parametrize(
    "pieces",
    [
        ['<tool_call>{"name": "open_app", ', '"arguments": {"name": "x"}}</tool_call>'],
        ['{"name": "open_app", ', '"arguments": {"name": "x"}}'],
        ["```json\n", '{"name": "open_app", "arguments": {"name": "x"}}\n```'],
    ],
)
async def test_a_call_written_as_text_is_never_spoken(pieces: list[str]) -> None:
    result, fed, _ = await _stream([_chunk(p) for p in pieces])
    assert fed == []
    assert [c.name for c in result.tool_calls] == ["open_app"]
    assert result.parsed_from_text


async def test_text_before_a_tag_is_spoken_and_the_tag_is_not() -> None:
    call = '<tool_call>{"name": "open_app", "arguments": {"name": "x"}}</tool_call>'
    result, fed, _ = await _stream([_chunk("Sure. "), _chunk(call)])
    assert fed == ["Sure. "]
    assert result.text == "Sure."
    assert [c.name for c in result.tool_calls] == ["open_app"]


async def test_held_text_that_was_not_a_call_is_spoken_at_the_end() -> None:
    result, fed, _ = await _stream([_chunk("Use "), _chunk("<b> for bold.")])
    assert "".join(fed) == "Use <b> for bold."
    assert result.tool_calls == []


# The speech stream


async def test_sentences_go_out_as_they_complete() -> None:
    speech = SpeechStream()
    speech.feed("The weather today is sunny ")
    assert not speech.started
    speech.feed("and warm. Tomorrow it")
    assert speech.started
    speech.feed(" rains.")
    speech.finish()
    assert [s async for s in speech.sentences()] == [
        "The weather today is sunny and warm.",
        "Tomorrow it rains.",
    ]
    assert speech.closed


async def test_the_fallback_speaks_each_sentence_as_it_arrives() -> None:
    async def sentences() -> AsyncIterator[str]:
        yield "One."
        yield "Two."

    tts = FakeTTS()
    assert await speak_stream(tts, sentences()) is not None
    assert tts.spoken == ["One.", "Two."]


async def test_piper_makes_audio_per_sentence_and_plays_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pytest.importorskip("jarvis.voice.tts.piper_engine")
    from jarvis.voice.tts.piper_engine import PiperTTS

    played: list[int] = []

    class Player:
        def play(self, samples: Any, rate: int) -> bool:
            played.append(int(samples[0]))
            return True

        def stop(self) -> None:
            return None

    tts = PiperTTS("voice", models_dir=None, player=Player())  # type: ignore[arg-type]
    made: list[str] = []

    def synthesize(text: str) -> tuple[Any, int]:
        made.append(text)
        return np.full(4, len(made), dtype=np.int16), 22_050

    monkeypatch.setattr(tts, "synthesize", synthesize)

    async def sentences() -> AsyncIterator[str]:
        yield "The first sentence is here."
        yield "And here is the second one."

    assert await tts.speak_stream(sentences()) is not None
    assert made == ["The first sentence is here.", "And here is the second one."]
    assert played == [1, 2]


# The whole turn


class StreamingLLM(FakeLLM):
    """A FakeLLM that also streams: each scripted reply's text arrives word by word."""

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        on_text: Callable[[str], None],
    ) -> LLMReply:
        result = await self.complete(messages, tools)
        for word in result.text.split(" "):
            on_text(f"{word} ")
        return result


async def test_a_spoken_reply_streams_and_is_not_said_twice(make_app: MakeApp) -> None:
    text = "It is sunny in Hyderabad today. Expect a warm evening."
    h = make_app(llm=StreamingLLM([reply(text)]))
    session, mic, _, tts = make_session(h, FakeSTT("what's the weather like"))
    await push_to_talk(session, mic)
    await until(lambda: len(tts.spoken) == 2)
    assert tts.spoken == ["It is sunny in Hyderabad today.", "Expect a warm evening."]

    def first_audio_recorded() -> bool:
        rows = h.app.history.recent()  # the speech can end before the turn is written down
        return bool(rows) and "first_audio_ms" in (rows[0]["timings_json"] or "")

    await until(first_audio_recorded)
    timings = json.loads(h.app.history.recent()[0]["timings_json"])
    assert timings["first_audio_ms"] >= 0
    assert "first_token_ms" in timings


async def test_words_before_a_tool_call_stop_the_stream(make_app: MakeApp, launched: list) -> None:
    llm = StreamingLLM(
        [
            reply("Let me get that open for you.", ("open_app", {"name": "notepad"})),
            reply("Notepad is open now."),
        ]
    )
    h = make_app(llm=llm)
    session, mic, _, tts = make_session(h, FakeSTT("could you get notepad up"))
    await push_to_talk(session, mic)
    await until(lambda: len(tts.spoken) == 2)
    # The stream closed at the tool call; the answer was spoken whole after the turn.
    assert tts.spoken == ["Let me get that open for you.", "Notepad is open now."]
    assert [entry.name for entry in launched] == ["Notepad"]


async def test_streaming_can_be_turned_off(make_app: MakeApp) -> None:
    h = make_app(llm=StreamingLLM([reply("One sentence here. And a second one.")]))
    h.app.settings.tts.stream = False
    session, mic, _, tts = make_session(h, FakeSTT("tell me something"))
    await push_to_talk(session, mic)
    await until(lambda: tts.spoken != [])
    assert tts.spoken == ["One sentence here. And a second one."]
