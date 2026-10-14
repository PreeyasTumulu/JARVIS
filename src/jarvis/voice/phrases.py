"""Deterministic handling of short spoken phrases: stop commands, yes or no, wake word cleanup.

These never go through the LLM, so "stop" works even when the model is slow, and a confirmation
needs one of a few clear affirmatives. Anything else counts as no.
"""

from __future__ import annotations

import re

_STOP = {
    "stop",
    "stop it",
    "stop that",
    "cancel",
    "cancel that",
    "never mind",
    "nevermind",
    "be quiet",
    "quiet",
    "shut up",
    "that's enough",
    "enough",
}
_YES = {
    "yes",
    "yeah",
    "yep",
    "yes please",
    "yes do it",
    "yes go ahead",
    "yes send it",
    "confirm",
    "confirmed",
    "go ahead",
    "do it",
    "send it",
    "affirmative",
}
_WAKE_PREFIX = re.compile(r"^(?:(?:hey|hi|ok|okay)\s+)?jarvis\b[\s,.!?]*", re.IGNORECASE)
_HALLUCINATIONS = {"", "you", "thank you", "thanks for watching", "bye", "so"}


def normalize(text: str) -> str:
    text = text.casefold().replace(chr(0x2019), "'")  # curly apostrophe
    text = re.sub(r"[^\w\s']", " ", text)
    return " ".join(text.split())


def strip_wake_word(text: str) -> str:
    return _WAKE_PREFIX.sub("", text.strip()).strip()


def is_stop_command(text: str) -> bool:
    words = normalize(strip_wake_word(text)).removesuffix(" please").removeprefix("please ")
    return words in _STOP or words.removeprefix("jarvis ") in _STOP


def parse_yes(text: str) -> bool:
    """True only for a clear affirmative. Silence, "no", or anything unclear is False."""
    words = normalize(strip_wake_word(text))
    return words in _YES or words.removesuffix(" please") in _YES


def clean_transcript(text: str) -> str:
    """Drop Whisper's typical silence hallucinations and a leading wake word."""
    text = " ".join(text.split())
    if normalize(text) in _HALLUCINATIONS:
        return ""
    return strip_wake_word(text)
