"""Voice as a UserChannel: confirmations and clarifying questions are spoken and answered aloud."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from jarvis.core.channel import ConfirmationRequest
from jarvis.voice.phrases import normalize, parse_yes

if TYPE_CHECKING:
    from jarvis.voice.session import VoiceSession

_ORDINALS = {
    "first": 0, "one": 0, "1": 0,
    "second": 1, "two": 1, "2": 1,
    "third": 2, "three": 2, "3": 2,
    "fourth": 3, "four": 3, "4": 3,
}  # fmt: skip


class VoiceChannel:
    name = "voice"

    def __init__(self) -> None:
        self._session: VoiceSession | None = None

    def attach(self, session: VoiceSession) -> None:
        self._session = session

    async def confirm(self, request: ConfirmationRequest) -> bool:
        question = f"Should I {_lower_first(request.summary)}? Say yes or no."
        return parse_yes(await self._require().ask_and_listen(question))

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        prompt = question if not options else f"{question} Options: {', '.join(options)}."
        answer = await self._require().ask_and_listen(prompt)
        return match_option(answer, options) if options else answer

    def _require(self) -> VoiceSession:
        if self._session is None:
            raise RuntimeError("VoiceChannel used before a VoiceSession was attached")
        return self._session


def match_option(answer: str, options: Sequence[str]) -> str:
    """Map "the second one" or "spotify" to an option; otherwise return the answer unchanged."""
    spoken = normalize(answer)
    for option in options:
        if normalize(option) and normalize(option) in spoken:
            return option
    for word in spoken.split():
        index = _ORDINALS.get(word)
        if index is not None and index < len(options):
            return options[index]
    return answer


def _lower_first(text: str) -> str:
    return text[:1].lower() + text[1:] if text else text
