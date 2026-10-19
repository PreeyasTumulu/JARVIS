"""Turn what you said ("option two", "the React one", "one and three") into an option label.

No model is involved: an answer to Claude, or a permission, must be exactly what you said, so
matching is by number, by name, or not at all.
"""

from __future__ import annotations

import re
from collections.abc import Sequence

from rapidfuzz import fuzz

from jarvis.voice.phrases import normalize, parse_yes

NUMBERS = {
    "one": 1, "first": 1, "1": 1, "won": 1,
    "two": 2, "second": 2, "2": 2, "to": 2, "too": 2,
    "three": 3, "third": 3, "3": 3,
    "four": 4, "fourth": 4, "4": 4, "for": 4,
    "five": 5, "fifth": 5, "5": 5,
    "six": 6, "sixth": 6, "6": 6,
}  # fmt: skip
# Words that may stand for numbers only right after "option" or "number" ("to" is too common).
LOOSE = {"won", "to", "too", "for"}
NAME_MATCH = 75  # rapidfuzz score an option name must reach (Whisper hears "reakt")
NAME_MARGIN = 10  # and by how much it must beat the next option
ORDINALS = {"first", "second", "third", "fourth", "fifth", "sixth"}
_OTHER = re.compile(r"^(?:other|something else|none of them)[\s,:.-]+(.+)$", re.IGNORECASE)
_NO = {"no", "nope", "deny", "denied", "don't", "do not", "stop", "cancel", "reject", "never"}
_ALLOW = {"allow", "allow it", "approve", "approved", "yes allow it", "yes allow"}


def match_options(answer: str, options: Sequence[str], *, multi: bool = False) -> str | None:
    """The chosen label (labels joined by ", " when several may be chosen), or None.

    "other: use Svelte" returns "use Svelte", the free-text answer Claude's questions allow.
    """
    text = answer.strip()
    if not text or not options:
        return text or None
    if (other := _OTHER.match(text)) is not None:
        return other.group(1).strip()
    for option in options:  # the web page sends the label itself
        if text == option:
            return option
    chosen = _by_number(normalize(text), len(options)) or _by_name(text, options)
    if not chosen:
        return None
    labels = [options[i] for i in sorted(chosen)]
    if not multi:
        return labels[0] if len(labels) == 1 else None  # two answers to a one-answer question
    return ", ".join(labels)


def _by_number(spoken: str, count: int) -> set[int]:
    words = spoken.split()
    picked: set[int] = set()
    for position, word in enumerate(words):
        number = NUMBERS.get(word)
        if number is None:
            continue
        before = words[position - 1] if position else ""
        if word in LOOSE and before not in ("option", "number"):
            continue
        if word == "one" and before in ORDINALS:
            continue  # "the second one"
        if 1 <= number <= count:
            picked.add(number - 1)
    return picked


def _by_name(answer: str, options: Sequence[str]) -> set[int]:
    spoken = normalize(answer)
    exact = {
        i for i, option in enumerate(options) if normalize(option) and normalize(option) in spoken
    }
    if exact:
        return exact
    scores = [fuzz.WRatio(spoken, normalize(option)) for option in options]
    ranked = sorted(range(len(options)), key=lambda i: -scores[i])
    best = ranked[0]
    runner_up = scores[ranked[1]] if len(ranked) > 1 else 0.0
    clear = scores[best] >= NAME_MATCH and scores[best] - runner_up >= NAME_MARGIN
    return {best} if clear else set()


def yes_or_no(answer: str) -> bool | None:
    """True for a clear yes (or "Allow" from the page), False for a clear no, else None."""
    text = answer.strip()
    words = normalize(text)
    if words in _ALLOW or parse_yes(text):
        return True
    if words in _NO or any(words.startswith(f"{no} ") for no in _NO):
        return False
    return None
