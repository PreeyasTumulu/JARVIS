"""Find the item a spoken or typed name refers to: an exact name first, else a clear fuzzy best."""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from typing import TypeVar

from rapidfuzz import fuzz

T = TypeVar("T")

MATCH_SCORE = 80
TIE_POINTS = 3
_FILLER = re.compile(
    r"\b(the|a|an|button|menu item|menu|tab|link|option|checkbox|check box|field|box)\b"
)
_SHORTCUT = re.compile(r"\s*\((?:ctrl|alt|shift)[^)]*\)\s*$", re.IGNORECASE)


def clean(name: str) -> str:
    """Lowercase, without filler words ("the Save button") or shortcut hints ("Bold (Ctrl+B)")."""
    return " ".join(_FILLER.sub(" ", _SHORTCUT.sub("", name).casefold()).split())


def pick(
    wanted: str,
    items: Sequence[T],
    name: Callable[[T], str],
    *,
    score: float = MATCH_SCORE,
) -> tuple[T | None, T | None]:
    """(best, rival). best is None when nothing is close; a rival means the name is unclear."""
    pool = [item for item in items if name(item)]
    plain = wanted.casefold().strip()
    target = clean(wanted) or plain
    exact = [item for item in pool if name(item).casefold().strip() == plain]
    exact = exact or [item for item in pool if clean(name(item)) == target]
    if exact:
        return exact[0], None
    scored = sorted(
        ((fuzz.WRatio(target, clean(name(item))), item) for item in pool),
        key=lambda pair: -pair[0],
    )
    if not scored or scored[0][0] < score:
        return None, None
    best_score, best = scored[0]
    for other_score, other in scored[1:]:
        if best_score - other_score > TIE_POINTS:
            break
        if clean(name(other)) != clean(name(best)):
            return best, other
    return best, None
