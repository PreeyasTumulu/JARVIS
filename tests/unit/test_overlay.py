"""The wake overlay: what it shows and when, its animation, its words, and its process pipe."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from jarvis.core.channel import ConfirmationRequest
from jarvis.core.events import (
    AssistantMessage,
    ConfirmationRequested,
    ConfirmationResolved,
    ToolCallFinished,
    ToolCallStarted,
    TranscriptHeard,
    TranscriptPartial,
    TurnFinished,
    VoiceLevel,
    VoiceStateChanged,
)
from jarvis.overlay.card import CardText, render_card, wrap
from jarvis.overlay.client import OverlayClient
from jarvis.overlay.director import Director
from jarvis.overlay.scene import PALETTE, Scene, targets_for
from jarvis.voice.session import voice_level

STATIC = Path(__file__).resolve().parents[2] / "src" / "jarvis" / "server" / "static"


def directed() -> tuple[Director, list[dict[str, Any]]]:
    sent: list[dict[str, Any]] = []
    return Director(sent.append), sent


def kinds(sent: list[dict[str, Any]]) -> list[str]:
    return [message["t"] for message in sent]


def last_text(sent: list[dict[str, Any]]) -> dict[str, Any]:
    return [message for message in sent if message["t"] == "text"][-1]


def request(summary: str = "Send hello to Amma") -> ConfirmationRequest:
    return ConfirmationRequest("r1", "send_whatsapp", summary, "digest", None, 30)


# When it opens


def test_listening_wakes_it_once() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("listening", "speak now"))
    director.on_event(VoiceStateChanged("transcribing"))
    assert director.active
    assert kinds(sent).count("wake") == 1
    assert sent[0] == {"t": "wake"}


def test_a_typed_turn_never_opens_it() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("thinking"))
    director.on_event(ToolCallStarted("t", "c", "open_app", {}, "safe"))
    director.on_event(AssistantMessage("t", "Done."))
    director.on_event(TurnFinished("t", "ok", 10))
    assert sent == []
    assert not director.active


def test_a_spoken_reminder_never_opens_it() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("speaking"))
    director.on_event(VoiceStateChanged("idle"))
    assert sent == []


@pytest.mark.parametrize(
    ("state", "detail"),
    [("listening", "dictating: release to type"), ("transcribing", "dictation")],
)
def test_dictation_never_opens_it(state: str, detail: str) -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged(state, detail))
    director.on_event(VoiceStateChanged("idle"))
    assert sent == []
    assert not director.active


def test_waiting_for_an_answer_opens_it_with_the_exact_question() -> None:
    director, sent = directed()
    director.on_event(ConfirmationRequested("t", request('Send "hi" to Amma')))
    director.on_event(VoiceStateChanged("awaiting_answer", "say it after the beep"))
    text = last_text(sent)
    assert text["heading"] == "Say yes or no"
    assert text["body"] == 'Send "hi" to Amma'
    assert text["tone"] == "confirm"


def test_a_partial_transcript_cannot_replace_the_question() -> None:
    director, sent = directed()
    director.on_event(ConfirmationRequested("t", request("Send hi to Amma")))
    director.on_event(VoiceStateChanged("awaiting_answer"))
    director.on_event(TranscriptPartial("ye"))
    assert last_text(sent)["body"] == "Send hi to Amma"
    director.on_event(ConfirmationResolved("t", "r1", "confirmed", "voice"))
    assert last_text(sent)["tone"] == "normal"


# What it shows


def test_words_arrive_as_you_speak_then_the_final_text() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("listening"))
    director.on_event(TranscriptPartial("open do"))
    assert last_text(sent)["body"] == "open do"
    director.on_event(TranscriptHeard("open docker", 900, 130))
    assert last_text(sent)["body"] == "open docker"


def test_tool_arguments_are_never_shown() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("listening"))
    director.on_event(ToolCallStarted("t", "c", "read_file", {"path": "secret-plans.txt"}, "safe"))
    assert last_text(sent)["status"] == "Running read_file"
    assert "secret-plans" not in json.dumps(sent)
    director.on_event(ToolCallFinished("t", "c", "read_file", "auto", True, "secret text", 5))
    assert last_text(sent)["status"] == ""
    assert "secret text" not in json.dumps(sent)


def test_level_is_only_sent_while_open() -> None:
    director, sent = directed()
    director.on_event(VoiceLevel(0.5))
    assert sent == []
    director.on_event(VoiceStateChanged("listening"))
    director.on_event(VoiceLevel(0.5))
    assert sent[-1] == {"t": "level", "v": 0.5}


# When it closes


def test_the_answer_lingers_after_jarvis_stops_speaking() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("listening"))
    director.on_event(VoiceStateChanged("thinking"))
    director.on_event(AssistantMessage("t", "Docker is open."))
    director.on_event(VoiceStateChanged("idle"))
    assert sent[-1]["t"] == "hide"
    assert sent[-1]["after"] > 0
    assert not director.active


def test_nothing_heard_and_stop_close_at_once() -> None:
    for detail in ("nothing heard", "stopped"):
        director, sent = directed()
        director.on_event(VoiceStateChanged("listening"))
        director.on_event(VoiceStateChanged("idle", detail))
        assert sent[-1] == {"t": "hide", "after": 0.0}


def test_stop_drops_the_answer_at_once_even_after_a_reply() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("listening"))
    director.on_event(AssistantMessage("t", "A long answer"))
    director.on_event(VoiceStateChanged("idle", "stopped"))
    assert sent[-1] == {"t": "hide", "after": 0.0}


def test_the_next_wake_starts_clean() -> None:
    director, sent = directed()
    director.on_event(VoiceStateChanged("listening"))
    director.on_event(TranscriptHeard("first command", 1, 1))
    director.on_event(VoiceStateChanged("idle"))
    sent.clear()
    director.on_event(VoiceStateChanged("listening"))
    assert kinds(sent)[0] == "wake"
    assert last_text(sent)["body"] == ""


# The animation


def test_full_screen_while_you_speak_then_it_recedes() -> None:
    speaking = targets_for("listening", mode="takeover", dim=0.7)
    working = targets_for("thinking", mode="takeover", dim=0.7)
    assert speaking.dim == 0.7
    assert speaking.core_size > working.core_size
    assert working.dim == 0.0
    assert working.sweep == 1.0


def test_edge_mode_never_dims_the_desktop() -> None:
    for state in ("listening", "awaiting_answer", "thinking"):
        assert targets_for(state, mode="edge", dim=0.7).dim == 0.0


def test_it_stops_drawing_after_it_fades() -> None:
    scene = Scene()
    scene.wake()
    scene.set_state("listening")
    for _ in range(120):
        scene.update(1 / 60)
    assert scene.visible
    assert scene.dim > 0.5
    scene.dismiss()
    for _ in range(240):
        scene.update(1 / 60)
    assert not scene.visible


def test_bars_follow_the_real_voice_while_listening() -> None:
    scene = Scene()
    scene.wake()
    scene.set_state("listening")
    scene.set_level(0.9)
    for _ in range(40):
        scene.update(1 / 60)
    assert max(scene.bars) > 0.5
    scene.set_level(0.0)
    for _ in range(120):
        scene.update(1 / 60)
    assert scene.level < 0.05


def test_the_page_uses_the_same_colours() -> None:
    script = (STATIC / "reactor.js").read_text(encoding="utf-8")
    for state, (first, second) in PALETTE.items():
        for value in (*first, *second):
            assert repr(value).removesuffix("0") in script or repr(value) in script, state


def test_both_renderers_share_one_shader_with_no_version_line() -> None:
    shader = (STATIC / "reactor.glsl").read_text(encoding="utf-8")
    assert not any(line.startswith("#version") for line in shader.splitlines())  # each adds its own
    assert "out vec4 fragColor" in shader


# The words


def measure(text: str) -> int:
    return len(text) * 10


def test_wrap_fits_the_width() -> None:
    lines = wrap("open docker and show me the logs", 120, measure, 3)
    assert all(measure(line) <= 120 for line in lines)
    assert " ".join(lines) == "open docker and show me the logs"


def test_wrap_marks_text_it_had_to_cut() -> None:
    lines = wrap(" ".join(["word"] * 60), 100, measure, 2)
    assert len(lines) == 2
    assert lines[-1].endswith("...")


def test_wrap_keeps_the_last_word_when_it_just_fits_the_limit() -> None:
    assert wrap("aaaa bbbb", 40, measure, 2) == ["aaaa", "bbbb"]


@pytest.mark.parametrize("big", [True, False])
def test_card_is_premultiplied(big: bool) -> None:
    image = render_card(
        CardText(heading="Listening", body="open docker"), width=800, big=big, scale=1.0
    )
    pixels = np.asarray(image, dtype=np.uint8)
    assert image.width == 800
    assert pixels[..., 3].max() > 0
    assert (pixels[..., :3].max(axis=-1) <= pixels[..., 3]).all()


def test_card_handles_empty_text() -> None:
    assert render_card(CardText(), width=400, big=True, scale=1.0).height > 0


# The process


class FakePipe:
    def __init__(self, fail_after: int | None = None) -> None:
        self.lines: list[bytes] = []
        self.fail_after = fail_after
        self.closed = False

    def write(self, data: bytes) -> int:
        if self.fail_after is not None and len(self.lines) >= self.fail_after:
            raise OSError("pipe broken")
        self.lines.append(data)
        return len(data)

    def flush(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, pipe: FakePipe, code: int | None = None) -> None:
        self.stdin = pipe
        self.code = code

    def poll(self) -> int | None:
        return self.code


def wait_for(check: Any, seconds: float = 3.0) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if check():
            return
        time.sleep(0.01)
    raise AssertionError("timed out")


def test_client_sends_the_config_first_then_messages() -> None:
    pipe = FakePipe()
    client = OverlayClient({"dim": 0.5}, lambda: FakeProcess(pipe))  # type: ignore[arg-type,return-value]
    client.start()
    client.send({"t": "wake"})
    wait_for(lambda: len(pipe.lines) == 2)
    assert json.loads(pipe.lines[0]) == {"dim": 0.5}
    assert json.loads(pipe.lines[1]) == {"t": "wake"}
    client.close()
    assert pipe.closed


def test_a_full_queue_drops_messages_instead_of_blocking() -> None:
    client = OverlayClient({}, lambda: FakeProcess(FakePipe()))  # type: ignore[arg-type,return-value]
    started = time.monotonic()
    for _ in range(5000):  # never started, so nothing drains the queue
        client.send({"t": "level", "v": 0.1})
    assert time.monotonic() - started < 1.0


def test_no_graphics_is_not_retried(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.overlay.client.RESTART_WAIT_S", 0.0)
    launches: list[int] = []

    def launch() -> Any:
        launches.append(1)
        return FakeProcess(FakePipe(fail_after=0), code=3)

    client = OverlayClient({}, launch)
    client.start()
    assert client._thread is not None
    client._thread.join(timeout=3)
    assert launches == [1]


def test_a_crashing_process_is_retried_then_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.overlay.client.RESTART_WAIT_S", 0.0)
    launches: list[int] = []

    def launch() -> Any:
        launches.append(1)
        return FakeProcess(FakePipe(fail_after=0), code=1)

    client = OverlayClient({}, launch)
    client.start()
    assert client._thread is not None
    client._thread.join(timeout=3)
    assert len(launches) == 4  # the first try and three restarts


def test_overlay_module_imports_without_opening_a_window() -> None:
    code = "import jarvis.overlay.client, jarvis.overlay.director; print('ok')"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip() == "ok", out.stderr


# The voice level


def test_voice_level_scale() -> None:
    assert voice_level(np.zeros(1280, dtype=np.int16)) == 0.0
    assert voice_level(np.zeros(0, dtype=np.int16)) == 0.0
    speech = voice_level(np.full(1280, int(0.05 * 32768), dtype=np.int16))
    assert 0.3 < speech < 0.8
    assert voice_level(np.full(1280, 32767, dtype=np.int16)) == 1.0
