"""Media control and the fast path. Windows media sessions and media keys are faked."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.core.fast_path import fast_call
from jarvis.core.tool_routing import matched_groups
from jarvis.platform import media
from jarvis.platform.media import MediaState, app_name
from tests.conftest import MakeApp, reply


class FakeMedia:
    def __init__(self, state: MediaState | None = None) -> None:
        self.state = state
        self.pressed: list[str] = []
        self.keys: list[str] = []
        self.error: Exception | None = None
        self.refuse = False

    async def control(self, action: str) -> MediaState | None:
        if self.error is not None:
            raise self.error
        if self.state is None:
            return None
        if self.refuse:
            raise OSError(f"{self.state.app} did not accept {action}")
        self.pressed.append(action)
        return self.state

    async def current(self, *, details: bool = False) -> MediaState | None:
        return self.state


@pytest.fixture
def player(monkeypatch: pytest.MonkeyPatch) -> FakeMedia:
    fake = FakeMedia(MediaState("Spotify", "playing", "Lofi Beats", "Chillhop"))
    monkeypatch.setattr(media, "control", fake.control)
    monkeypatch.setattr(media, "current", fake.current)
    monkeypatch.setattr(media, "press_media_key", fake.keys.append)
    return fake


@pytest.mark.parametrize(
    ("app_id", "name"),
    [
        ("SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify", "Spotify"),
        ("Spotify.exe", "Spotify"),
        ("Microsoft.ZuneMusic_8wekyb3d8bbwe!Microsoft.ZuneMusic", "Media Player"),
        ("brave.exe", "Brave"),
        ("msedge.exe", "Edge"),
        ("Chrome", "Chrome"),
        ("SomeApp", "SomeApp"),
        ("", ""),
    ],
)
def test_app_names(app_id: str, name: str) -> None:
    assert app_name(app_id) == name


async def call(h: Any, tool: str, **args: Any) -> Any:
    import json

    from jarvis.llm.types import ToolCall
    from jarvis.tools.base import ToolContext

    ctx = ToolContext(
        settings=h.app.settings,
        channel=h.channel,
        services=h.app.services,
        session_id="s",
        turn_id="t",
    )
    outcome = await h.app.agent._executor.run(ToolCall("c1", tool, json.dumps(args)), ctx)
    return outcome.result


@pytest.mark.parametrize(
    ("action", "speech"),
    [
        ("pause", "Paused in Spotify."),
        ("play", "Playing in Spotify."),
        ("next", "Skipped to the next track in Spotify."),
        ("previous", "Back to the previous track in Spotify."),
        ("toggle", "Paused in Spotify."),  # it was playing
    ],
)
async def test_media_control(
    make_app: MakeApp, player: FakeMedia, action: str, speech: str
) -> None:
    h = make_app()
    result = await call(h, "media_control", action=action)
    assert result.ok
    assert result.speech == speech
    assert player.pressed == [action]
    assert player.keys == []
    assert "Lofi" not in str(result.data)  # the public tool never carries the title


async def test_pause_with_nothing_playing_presses_nothing(
    make_app: MakeApp, player: FakeMedia
) -> None:
    player.state = None
    result = await call(make_app(), "media_control", action="pause")
    assert result.speech == "Nothing is playing."
    assert player.keys == []


async def test_play_with_no_session_presses_the_media_key(
    make_app: MakeApp, player: FakeMedia
) -> None:
    player.state = None
    result = await call(make_app(), "media_control", action="play")
    assert result.ok
    assert player.keys == ["play"]


async def test_broken_media_sessions_fall_back_to_the_keys(
    make_app: MakeApp, player: FakeMedia
) -> None:
    player.error = RuntimeError("no winrt")
    result = await call(make_app(), "media_control", action="next")
    assert result.ok
    assert player.keys == ["next"]
    assert result.data["via"] == "media key"


async def test_an_app_that_refuses_is_reported(make_app: MakeApp, player: FakeMedia) -> None:
    player.refuse = True
    result = await call(make_app(), "media_control", action="next")
    assert not result.ok
    assert "Spotify did not accept next" in result.error


async def test_now_playing(make_app: MakeApp, player: FakeMedia) -> None:
    result = await call(make_app(), "now_playing")
    assert result.speech == "Spotify is playing Lofi Beats by Chillhop."

    player.state = MediaState("Brave", "paused")
    result = await call(make_app(), "now_playing")
    assert result.speech == "Brave has paused something, but it doesn't say what."

    player.state = None
    result = await call(make_app(), "now_playing")
    assert result.speech == "Nothing is playing."


def test_now_playing_is_private_and_media_control_public(make_app: MakeApp) -> None:
    registry = make_app().app.registry
    assert registry.get("now_playing").sensitivity.value == "private"
    assert registry.get("media_control").sensitivity.value == "public"


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("pause", ("media_control", '{"action": "pause"}')),
        ("Pause the music.", ("media_control", '{"action": "pause"}')),
        ("Hey Jarvis, pause the music please", ("media_control", '{"action": "pause"}')),
        ("stop the music", ("media_control", '{"action": "pause"}')),
        ("resume", ("media_control", '{"action": "play"}')),
        ("play", ("media_control", '{"action": "play"}')),
        ("Next song.", ("media_control", '{"action": "next"}')),
        ("skip this song", ("media_control", '{"action": "next"}')),
        ("previous track", ("media_control", '{"action": "previous"}')),
        ("What's playing?", ("now_playing", "{}")),
        ("what song is this", ("now_playing", "{}")),
        # Anything longer, or not clearly media, goes to the model.
        ("play lofi music on youtube", None),
        ("pause the timer", None),
        ("next", None),
        ("stop", None),
        ("stop it", None),
        ("what's playing at the cinema tonight", None),
    ],
)
def test_fast_path_phrases(text: str, expected: tuple[str, str] | None) -> None:
    assert fast_call(text) == expected


async def test_a_fast_command_skips_the_model(make_app: MakeApp, player: FakeMedia) -> None:
    h = make_app()  # no scripted replies: any model call would fail the turn
    result = await h.app.agent.run_turn("pause the music")
    assert result.text == "Paused in Spotify."
    assert h.llm.requests == []
    assert result.model == "fast path"
    assert result.iterations == 0
    (row,) = h.audit()
    assert row["tool"] == "media_control"
    assert row["decision"] == "auto"
    assert "first_tool_ms" in result.timings


async def test_after_a_fast_command_the_model_sees_what_happened(
    make_app: MakeApp, player: FakeMedia
) -> None:
    h = make_app([reply("It was Lofi Beats.")])
    await h.app.agent.run_turn("what's playing")
    await h.app.agent.run_turn("who was that again")
    roles = [m["role"] for m in h.llm.requests[0][1:]]
    assert roles == ["user", "assistant", "tool", "assistant", "user"]


def test_media_requests_route_to_the_media_tools() -> None:
    assert "media" in matched_groups("play some lofi music")
    assert "media" in matched_groups("skip to the next track please")
    assert "media" in matched_groups("who sings this")
