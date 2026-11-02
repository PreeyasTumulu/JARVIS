"""Dictation: hold a hotkey, speak, and the text appears where the cursor is, in any app (ADR-054).

No model touches the text. Whisper already punctuates; rules then turn spoken commands into
punctuation ("new line", "comma", "full stop") and drop fillers ("um", "uh"). Short text is
typed as Unicode keystrokes, so the clipboard is untouched. Longer text is pasted, because
typing is paced for slow apps (about 12 ms a character): the clipboard is borrowed, marked to
stay out of Win+V history, and put back afterwards.

Line breaks are Shift+Enter, never Enter, so a "new line" in a chat box cannot send the message.
"""

from __future__ import annotations

import logging
import os
import re
import time

from jarvis.config import DictationSettings
from jarvis.platform import clipboard, sendinput, windows

log = logging.getLogger(__name__)

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_RETURN = 0x0D
VK_V = 0x56
MODIFIER_KEYS = (VK_SHIFT, VK_CONTROL, VK_MENU, 0x5B, 0x5C)  # and both Windows keys
RELEASE_WAIT_S = 2.0  # the hotkey's Ctrl and Alt may still be down when its letter comes up
PASTE_SETTLE_S = 0.5  # apps read a pasted clipboard late; restoring sooner pastes the old text

_PUNCT = r"[ \t,.;:!?]*"  # Whisper's own punctuation around a command; never a line break
_COMMANDS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(rf"{_PUNCT}\bnew paragraph\b{_PUNCT}", re.IGNORECASE), "\n\n"),
    (re.compile(rf"{_PUNCT}\bnew line\b{_PUNCT}", re.IGNORECASE), "\n"),
    (re.compile(rf"{_PUNCT}\bfull stop\b{_PUNCT}", re.IGNORECASE), ". "),
    (re.compile(rf"{_PUNCT}\bquestion mark\b{_PUNCT}", re.IGNORECASE), "? "),
    (re.compile(rf"{_PUNCT}\bexclamation (?:mark|point)\b{_PUNCT}", re.IGNORECASE), "! "),
    (re.compile(rf"{_PUNCT}\bsemicolon\b{_PUNCT}", re.IGNORECASE), "; "),
    (re.compile(rf"{_PUNCT}\bcomma\b{_PUNCT}", re.IGNORECASE), ", "),
    # "period" is also a word ("a trial period"), so only as the very last word.
    (re.compile(rf"{_PUNCT}\bperiod{_PUNCT}$", re.IGNORECASE), "."),
]
# A filler takes the comma Whisper put before it: "we should, uh, ship it" is "we should ship it".
_FILLERS = re.compile(
    r"(?:,\s*)?(?<![\w'])(?:u+m+|u+h+|e+r+m+|hm+|mm+)(?![\w']),?\s*", re.IGNORECASE
)
_SENTENCE_START = re.compile(r"(^|[.?!]\s+|\n\s*)([a-z])")


class DictationError(Exception):
    """Something to tell the user: the text could not be put anywhere."""


def format_dictation(
    text: str, *, spoken_commands: bool = True, remove_fillers: bool = True
) -> str:
    """Whisper's text as it should land in the document."""
    text = " ".join(text.split())
    if remove_fillers:
        text = _FILLERS.sub(" ", text)
    if spoken_commands:
        for pattern, replacement in _COMMANDS:
            text = pattern.sub(replacement, text)
    text = re.sub(r"[ \t]*\n[ \t]*", "\n", text)
    text = re.sub(r" {2,}", " ", text)
    text = re.sub(r" ([,.;:!?])", r"\1", text).strip(" ")
    if not re.search(r"\w", text):
        return ""  # only a filler and its punctuation
    text = _SENTENCE_START.sub(lambda m: m.group(1) + m.group(2).upper(), text)
    if text and text[-1] in ".?!,;:":
        text += " "  # the next dictation then starts a new word
    return text


class Inserter:
    """Puts dictated text into the focused window. Blocking: call it from a worker thread."""

    def __init__(self, cfg: DictationSettings) -> None:
        self._cfg = cfg

    def insert(self, text: str) -> str:
        """Format and insert. Returns "typed", "pasted", or "" when nothing was left to insert."""
        text = format_dictation(
            text,
            spoken_commands=self._cfg.spoken_commands,
            remove_fillers=self._cfg.remove_fillers,
        )
        if not text.strip():
            return ""
        if not sendinput.wait_for_keys_released(MODIFIER_KEYS, RELEASE_WAIT_S):
            # Typed with Ctrl held, "a" would select everything and "w" close the tab.
            raise DictationError("A key is still held down, so I didn't type anything.")
        self._check_target()
        if len(text) <= self._cfg.paste_over_chars or not self._can_borrow_clipboard():
            self._type(text)
            return "typed"
        self._paste(text)
        return "pasted"

    @staticmethod
    def _check_target() -> None:
        hwnd = windows.foreground_window()
        if not hwnd:
            raise DictationError("No window has the focus, so there is nowhere to type.")
        pid = windows.window_pid(hwnd)
        if pid and sendinput.is_elevated(pid) and not sendinput.is_elevated(os.getpid()):
            raise DictationError(
                "That window runs as administrator, so Windows blocks typing into it."
            )

    @staticmethod
    def _can_borrow_clipboard() -> bool:
        """Only text can be put back, so an image or copied files on the clipboard mean typing."""
        try:
            return not clipboard.holds_other_data()
        except OSError:
            return False

    @staticmethod
    def _type(text: str) -> None:
        for index, line in enumerate(text.split("\n")):
            if index:
                sendinput.press_combo([VK_SHIFT], VK_RETURN)
            if line:
                sendinput.type_unicode(line)

    def _paste(self, text: str) -> None:
        try:
            previous = clipboard.get_text()
            clipboard.set_text(text, private=True)
        except OSError as exc:
            log.info("Clipboard busy (%s); typing the dictation instead", exc)
            self._type(text)
            return
        try:
            sendinput.press_combo([VK_CONTROL], VK_V)
            time.sleep(PASTE_SETTLE_S)
        finally:
            try:
                if previous is None:
                    clipboard.clear()
                else:
                    clipboard.set_text(previous, private=True)
            except OSError:
                log.warning("Could not put the clipboard back after dictation")
