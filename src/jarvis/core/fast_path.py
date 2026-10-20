"""Exact short commands that run a tool without asking the model (ADR-056).

"Pause the music" needs no reasoning, and waiting 2 to 3 seconds for an 8B model to pick
media_control makes it feel broken. Only whole, exact phrases match, after the wake word and a
"please" are removed, so anything longer or unusual still goes to the model. The call still goes
through the executor: the policy gate, the audit log, and the events all see it.
"""

from __future__ import annotations

import json

from jarvis.voice.phrases import normalize, strip_wake_word

_MEDIA_NOUNS = ("", " the music", " music", " the song", " the video", " it", " playback")

MEDIA: dict[str, str] = {
    **{f"pause{noun}": "pause" for noun in _MEDIA_NOUNS},
    **{f"resume{noun}": "play" for noun in _MEDIA_NOUNS},
    **{f"unpause{noun}": "play" for noun in _MEDIA_NOUNS},
    **{f"stop{noun}": "pause" for noun in _MEDIA_NOUNS if noun not in ("", " it")},
    "play": "play",
    "play the music": "play",
    "play music": "play",
    "continue playing": "play",
    "keep playing": "play",
    **{f"{verb} {noun}": "next" for verb in ("next", "skip") for noun in ("song", "track")},
    **{f"skip {noun}": "next" for noun in ("this song", "this track", "this", "it")},
    "skip": "next",
    "play the next song": "next",
    "play next song": "next",
    **{f"{verb} {noun}": "previous" for verb in ("previous", "last") for noun in ("song", "track")},
    "play the previous song": "previous",
    "play previous song": "previous",
    "go back a song": "previous",
}
BRIEFING = {
    "good morning",
    "brief me",
    "morning briefing",
    "my briefing",
    "give me my briefing",
    "daily briefing",
    "what's my day look like",
    "how does my day look",
    "how does my day look like",
    "what does my day look like",
}
NOW_PLAYING = {
    "what's playing",
    "what is playing",
    "what's this song",
    "what is this song",
    "what song is this",
    "which song is this",
    "what song is playing",
    "what's the song",
    "who sings this",
}


def _phrase(text: str) -> str:
    words = normalize(strip_wake_word(text)).removeprefix("please ").removesuffix(" please")
    return words.removesuffix(" jarvis").removesuffix(" now")


def fast_call(text: str) -> tuple[str, str] | None:
    """The tool name and JSON arguments for an exact short command, or None."""
    phrase = _phrase(text)
    if phrase in MEDIA:
        return "media_control", json.dumps({"action": MEDIA[phrase]})
    if phrase in NOW_PLAYING:
        return "now_playing", "{}"
    if phrase in BRIEFING:
        return "briefing", "{}"
    return None
