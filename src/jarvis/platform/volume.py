"""Master speaker volume through the Windows Core Audio API (pycaw). Call on the COM thread."""

from __future__ import annotations

from typing import Any


def _endpoint() -> Any:
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


def get_volume() -> tuple[int, bool]:
    """(level 0 to 100, muted) of the default playback device."""
    endpoint = _endpoint()
    return round(endpoint.GetMasterVolumeLevelScalar() * 100), bool(endpoint.GetMute())


def set_volume(level: int | None = None, mute: bool | None = None) -> tuple[int, bool]:
    """Change the level and/or mute state, then return the new (level, muted)."""
    endpoint = _endpoint()
    if level is not None:
        endpoint.SetMasterVolumeLevelScalar(max(0, min(100, level)) / 100, None)
    if mute is not None:
        endpoint.SetMute(int(mute), None)
    return round(endpoint.GetMasterVolumeLevelScalar() * 100), bool(endpoint.GetMute())
