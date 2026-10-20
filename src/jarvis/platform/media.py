"""Media playback through Windows media sessions, with the media keys as a fallback (ADR-055).

Apps that play audio or video (Spotify, the Media Player, YouTube in Brave or Chrome) register
a media session with Windows, the same one the volume flyout shows. Through it Jarvis can tell
playing from paused, press the right button (play is not a toggle), and say what is playing.
Apps that do not register still answer the keyboard's media keys, sent with SendInput.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Literal

from jarvis.platform import sendinput

log = logging.getLogger(__name__)

Action = Literal["play", "pause", "toggle", "next", "previous"]

VK_MEDIA_NEXT_TRACK = 0xB0
VK_MEDIA_PREV_TRACK = 0xB1
VK_MEDIA_PLAY_PAUSE = 0xB3
MEDIA_KEYS: dict[str, int] = {
    "play": VK_MEDIA_PLAY_PAUSE,
    "pause": VK_MEDIA_PLAY_PAUSE,
    "toggle": VK_MEDIA_PLAY_PAUSE,
    "next": VK_MEDIA_NEXT_TRACK,
    "previous": VK_MEDIA_PREV_TRACK,
}
_METHODS: dict[str, str] = {
    "play": "try_play_async",
    "pause": "try_pause_async",
    "toggle": "try_toggle_play_pause_async",
    "next": "try_skip_next_async",
    "previous": "try_skip_previous_async",
}
# GlobalSystemMediaTransportControlsSessionPlaybackStatus
_STATUS = {0: "closed", 1: "opened", 2: "changing", 3: "stopped", 4: "playing", 5: "paused"}
# Store apps report a package id; the useful part is after "!", and some need a better name.
_APP_NAMES = {
    "zunemusic": "Media Player",
    "zunevideo": "Movies and TV",
    "msedge": "Edge",
    "spotify": "Spotify",
    "chrome": "Chrome",
    "brave": "Brave",
    "firefox": "Firefox",
    "vlc": "VLC",
}


@dataclass(frozen=True)
class MediaState:
    app: str  # a friendly app name, "" when Windows does not say
    status: str  # playing, paused, stopped, or another _STATUS value
    title: str = ""
    artist: str = ""


def app_name(app_id: str) -> str:
    """'SpotifyAB.SpotifyMusic_zpdnekdrzrea0!Spotify' to 'Spotify', 'brave.exe' to 'Brave'."""
    name = app_id.rsplit("!", 1)[-1].removesuffix(".exe").removesuffix(".EXE")
    key = name.rsplit(".", 1)[-1].casefold()
    return _APP_NAMES.get(key, _APP_NAMES.get(name.split(".", 1)[0].casefold(), name))


async def _session() -> Any:
    from winrt.windows.media.control import (
        GlobalSystemMediaTransportControlsSessionManager as Manager,
    )

    manager = await Manager.request_async()
    return manager.get_current_session()


def _state(session: Any, title: str = "", artist: str = "") -> MediaState:
    status = int(session.get_playback_info().playback_status)
    return MediaState(
        app_name(session.source_app_user_model_id or ""),
        _STATUS.get(status, "unknown"),
        title,
        artist,
    )


async def current(*, details: bool = False) -> MediaState | None:
    """The session Windows considers current, or None when nothing has one."""
    session = await _session()
    if session is None:
        return None
    if not details:
        return _state(session)
    props = await session.try_get_media_properties_async()
    return _state(session, props.title or "", props.artist or "")


async def control(action: Action) -> MediaState | None:
    """Press a button on the current session. Returns its state before the press, or None when
    there is no session. Raises OSError when the app refuses (a button it does not offer)."""
    session = await _session()
    if session is None:
        return None
    before = _state(session)
    if not await getattr(session, _METHODS[action])():
        raise OSError(f"{before.app or 'The app'} did not accept {action}")
    return before


def press_media_key(action: Action) -> None:
    """The keyboard's media key: play and pause are one toggle key."""
    sendinput.press_combo([], MEDIA_KEYS[action])
