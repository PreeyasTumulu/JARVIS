"""Dictation: the text rules, and inserting by typing or pasting. No real keystrokes are sent."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.config import DictationSettings
from jarvis.voice import dictation
from jarvis.voice.dictation import DictationError, Inserter, format_dictation


@pytest.mark.parametrize(
    ("heard", "written"),
    [
        ("Hello world", "Hello world"),
        ("hello there.", "Hello there. "),
        (
            "Hi Ravi, new line. I will be late today comma sorry.",
            "Hi Ravi\nI will be late today, sorry. ",
        ),
        ("Dear team new paragraph thanks full stop see you", "Dear team\n\nThanks. See you"),
        ("Is it ready question mark", "Is it ready? "),
        ("Hello Ravi comma new line thanks", "Hello Ravi,\nThanks"),
        ("Wow exclamation point", "Wow! "),
        ("first semicolon second", "First; second"),
        ("The trial period is over period", "The trial period is over. "),
        ("Um, so I think we should, uh, ship it.", "So I think we should ship it. "),
        ("I mean, hmm. Okay", "I mean. Okay"),
        ("Uh.", ""),
        # Real words that look like commands or fillers stay as they are.
        ("Take the next line of code", "Take the next line of code"),
        ("The period of time", "The period of time"),
        ("Umbrella and humming", "Umbrella and humming"),
    ],
)
def test_format(heard: str, written: str) -> None:
    assert format_dictation(heard) == written


def test_rules_can_be_turned_off() -> None:
    text = "um hello comma world"
    assert (
        format_dictation(text, spoken_commands=False, remove_fillers=False)
        == "Um hello comma world"
    )


class FakeWindows:
    def __init__(self) -> None:
        self.events: list[tuple[str, Any]] = []
        self.clipboard: str | None = "what you copied"
        self.other_data = False
        self.elevated: set[int] = set()
        self.hwnd = 7


@pytest.fixture
def win(monkeypatch: pytest.MonkeyPatch) -> FakeWindows:
    fake = FakeWindows()

    def set_text(text: str, *, private: bool = False) -> None:
        fake.clipboard = text
        fake.events.append(("clipboard", (text, private)))

    def clear() -> None:
        fake.clipboard = None
        fake.events.append(("clipboard", None))

    def combo(mods: list[int], key: int) -> None:
        fake.events.append(("combo", (tuple(mods), key)))
        if key == dictation.VK_V:
            fake.events.append(("pasted", fake.clipboard))

    monkeypatch.setattr(
        dictation.sendinput, "type_unicode", lambda t: fake.events.append(("type", t))
    )
    monkeypatch.setattr(dictation.sendinput, "press_combo", combo)
    monkeypatch.setattr(dictation.sendinput, "wait_for_keys_released", lambda *_: True)
    monkeypatch.setattr(dictation.sendinput, "is_elevated", lambda pid: pid in fake.elevated)
    monkeypatch.setattr(dictation.windows, "foreground_window", lambda: fake.hwnd)
    monkeypatch.setattr(dictation.windows, "window_pid", lambda hwnd: 42)
    monkeypatch.setattr(dictation.clipboard, "get_text", lambda: fake.clipboard)
    monkeypatch.setattr(dictation.clipboard, "set_text", set_text)
    monkeypatch.setattr(dictation.clipboard, "clear", clear)
    monkeypatch.setattr(dictation.clipboard, "holds_other_data", lambda: fake.other_data)
    monkeypatch.setattr(dictation, "PASTE_SETTLE_S", 0)
    return fake


def test_short_text_is_typed_and_the_clipboard_is_untouched(win: FakeWindows) -> None:
    assert Inserter(DictationSettings()).insert("hello there") == "typed"
    assert win.events == [("type", "Hello there")]
    assert win.clipboard == "what you copied"


def test_a_new_line_is_shift_enter_so_a_chat_box_does_not_send(win: FakeWindows) -> None:
    Inserter(DictationSettings()).insert("hi new line bye")
    assert win.events == [
        ("type", "Hi"),
        ("combo", ((dictation.VK_SHIFT,), dictation.VK_RETURN)),
        ("type", "Bye"),
    ]


def test_long_text_is_pasted_privately_and_the_clipboard_put_back(win: FakeWindows) -> None:
    text = "word " * 60
    assert Inserter(DictationSettings()).insert(text) == "pasted"
    pasted = format_dictation(text)
    assert ("clipboard", (pasted, True)) in win.events  # kept out of Win+V history
    assert ("pasted", pasted) in win.events
    assert win.events[-1] == ("clipboard", ("what you copied", True))
    assert win.clipboard == "what you copied"


def test_an_empty_clipboard_is_left_empty(win: FakeWindows) -> None:
    win.clipboard = None
    Inserter(DictationSettings(paste_over_chars=0)).insert("hello")
    assert win.clipboard is None


def test_an_image_on_the_clipboard_means_typing(win: FakeWindows) -> None:
    win.other_data = True
    assert Inserter(DictationSettings(paste_over_chars=0)).insert("hello") == "typed"
    assert not any(kind == "clipboard" for kind, _ in win.events)


def test_nothing_to_insert(win: FakeWindows) -> None:
    assert Inserter(DictationSettings()).insert("um") == ""
    assert win.events == []


def test_no_focused_window(win: FakeWindows) -> None:
    win.hwnd = 0
    with pytest.raises(DictationError, match="nowhere to type"):
        Inserter(DictationSettings()).insert("hello")


def test_nothing_is_typed_while_a_key_is_held(
    win: FakeWindows, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(dictation.sendinput, "wait_for_keys_released", lambda *_: False)
    with pytest.raises(DictationError, match="still held"):
        Inserter(DictationSettings()).insert("hello")
    assert win.events == []


def test_an_administrator_window_is_refused(win: FakeWindows) -> None:
    win.elevated = {42}
    with pytest.raises(DictationError, match="administrator"):
        Inserter(DictationSettings()).insert("hello")
    assert win.events == []


def test_dictation_hotkey_binding(settings: Any) -> None:
    from jarvis.voice.runner import hotkey_bindings

    assert hotkey_bindings(settings)["dictate"].text == "ctrl+alt+d"
    off = settings.model_copy(update={"dictation": DictationSettings(enabled=False)})
    assert "dictate" not in hotkey_bindings(off)
