"""UI automation: key parsing, risk rules, and the type, click, press, and read window tools."""

from __future__ import annotations

import pytest

from jarvis.config import SafetySettings
from jarvis.platform.uia import Control
from jarvis.tools.apps.index import AppEntry
from jarvis.tools.base import Risk, ToolError
from jarvis.tools.ui import guard
from jarvis.tools.ui.keys import describe, parse_keys
from jarvis.tools.ui.tools import CHUNK_CHARS, match_control
from tests.conftest import FakeChannel, FakeDesktop, MakeApp, reply

DOC = Control("document", "Text editor")
SAVE = Control("button", "Save")
DELETE = Control("button", "Delete all")
PASSWORD = Control("field", "Password", password=True)


def notepad(desktop: FakeDesktop, *controls: Control) -> int:
    window = desktop.add("Untitled - Notepad", "Notepad")
    desktop.controls[window.hwnd] = list(controls or (DOC, SAVE, DELETE))
    desktop.lines[window.hwnd] = ["Shopping list", "milk"]
    return window.hwnd


# Keys


def test_parse_keys_reads_shortcuts_and_sequences() -> None:
    assert describe(parse_keys("ctrl+s")) == "Ctrl+S"
    assert describe(parse_keys("Alt + F4, enter")) == "Alt+F4, Enter"
    assert describe(parse_keys("shift+ctrl+tab")) == "Ctrl+Shift+Tab"
    assert describe(parse_keys("page up")) == "PageUp"
    assert describe(parse_keys("ctrl++")) == "Ctrl+Plus"
    combo = parse_keys("ctrl+a")[0]
    assert combo.modifier_vks == (0x11,)
    assert combo.vk == ord("A")


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("win+r", "Windows key"),
        ("ctrl+", "no key"),
        ("hyper+x", "not a modifier"),
        ("ctrl+banana", "don't know"),
        ("", "No keys"),
        ("tab " * 21, "more than"),
    ],
)
def test_parse_keys_refuses_what_it_cannot_send(text: str, problem: str) -> None:
    with pytest.raises(ToolError, match=problem):
        parse_keys(text)


# Risk rules


def test_trusted_apps_run_directly_and_others_ask() -> None:
    safety = SafetySettings(trusted_ui_apps=["Notepad"])
    assert guard.app_ui_risk("Notepad", "Notepad", safety) == (Risk.SAFE, None)
    risk, reason = guard.app_ui_risk("Spotify", "Spotify", safety)
    assert risk is Risk.CONFIRM
    assert "trusted_ui_apps" in (reason or "")


def test_messaging_apps_and_terminals_always_ask_even_when_trusted() -> None:
    safety = SafetySettings(trusted_ui_apps=["WhatsApp", "Windows Terminal"])
    assert guard.app_ui_risk("WhatsApp", "WhatsApp.Root", safety)[0] is Risk.CONFIRM
    assert guard.app_ui_risk("Windows Terminal", "WindowsTerminal", safety)[0] is Risk.CONFIRM


def test_registry_editor_and_password_managers_are_blocked() -> None:
    safety = SafetySettings(trusted_ui_apps=["Registry Editor"])
    assert guard.app_ui_risk("Registry Editor", "regedit", safety)[0] is Risk.BLOCKED
    assert guard.app_ui_risk("KeePassXC", "KeePassXC", safety)[0] is Risk.BLOCKED


@pytest.mark.parametrize("label", ["Send", "Delete all", "Don't Save", "Buy now", "Sign out"])
def test_destructive_targets_ask(label: str) -> None:
    assert guard.target_risk(label)[0] is Risk.CONFIRM


@pytest.mark.parametrize("label", ["Save", "File", "Bold (Ctrl+B)", "Settings"])
def test_ordinary_targets_do_not_ask(label: str) -> None:
    assert guard.target_risk(label) == (Risk.SAFE, None)


def test_closing_shortcuts_ask() -> None:
    assert guard.keys_risk(parse_keys("alt+f4"))[0] is Risk.CONFIRM
    assert guard.keys_risk(parse_keys("ctrl+s, enter")) == (Risk.SAFE, None)


# Matching controls by name


def test_match_control_prefers_exact_names_and_ignores_filler() -> None:
    controls = [Control("button", "Bold (Ctrl+B)"), SAVE, Control("menu item", "Save as")]
    assert match_control(controls, "the Save button", "Notepad") == SAVE
    assert match_control(controls, "bold", "Notepad").name == "Bold (Ctrl+B)"


def test_match_control_reports_unknown_and_unclear_names() -> None:
    with pytest.raises(ToolError, match="Some that are: Save"):
        match_control([SAVE], "Print", "Notepad")
    twins = [Control("button", "Reply"), Control("button", "Reply all")]
    with pytest.raises(ToolError, match="Ask the user"):
        match_control(twins, "repl", "Mail")


# type_text


async def test_type_text_in_a_trusted_app_types_without_asking(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    hwnd = notepad(desktop)
    text = "hello world, this is longer than one chunk of typing"
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": text})), reply("Done.")])
    await h.app.agent.run_turn("type that in notepad")
    assert "".join(desktop.typed) == text
    assert len(desktop.typed) == -(-len(text) // CHUNK_CHARS)
    assert desktop.focused == [hwnd]
    assert h.channel.requests == []
    entry = h.audit()[0]
    assert (entry["decision"], entry["ok"]) == ("auto", 1)


async def test_type_text_starts_the_app_when_it_is_not_open(
    make_app: MakeApp, desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    def launch(entry: AppEntry) -> None:
        notepad(desktop)

    monkeypatch.setattr("jarvis.tools.apps.tools.launch", launch)
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": "hi"})), reply("Done.")])
    await h.app.agent.run_turn("type hi in notepad")
    assert desktop.typed == ["hi"]
    assert h.channel.requests == []  # Notepad is on the app allowlist and trusted


async def test_type_text_never_types_into_a_password_field(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    hwnd = notepad(desktop, PASSWORD)
    desktop.field[hwnd] = PASSWORD
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": "hunter2"})), reply("No.")])
    await h.app.agent.run_turn("type my password")
    assert desktop.typed == []
    assert h.audit()[0]["decision"] == "blocked"


async def test_type_text_checks_the_field_again_when_it_runs(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    # The focus is outside the window while preparing, then lands in a password box.
    notepad(desktop, PASSWORD)
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": "hunter2"})), reply("No.")])
    await h.app.agent.run_turn("type it")
    assert desktop.typed == []
    assert "password" in (h.audit()[0]["error"] or "")


async def test_type_text_stops_when_another_window_takes_the_focus(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    notepad(desktop)
    desktop.steal_focus_after = 1
    text = "x" * (CHUNK_CHARS * 3)
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": text})), reply("Stopped.")])
    await h.app.agent.run_turn("type a lot")
    assert desktop.typed == ["x" * CHUNK_CHARS]
    assert f"after {CHUNK_CHARS} characters" in (h.audit()[0]["error"] or "")


async def test_type_text_does_nothing_when_windows_refuses_the_focus(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    notepad(desktop)
    desktop.refuse_focus = True
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": "hi"})), reply("Sorry.")])
    await h.app.agent.run_turn("type hi")
    assert desktop.typed == []
    assert "did nothing" in (h.audit()[0]["error"] or "")


async def test_type_text_refuses_windows_running_as_administrator(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    window = desktop.add("Untitled - Notepad", "Notepad", pid=42)
    desktop.controls[window.hwnd] = [DOC]
    desktop.elevated.add(42)
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": "hi"})), reply("Sorry.")])
    await h.app.agent.run_turn("type hi")
    assert desktop.typed == []
    assert "administrator" in (h.audit()[0]["error"] or "")


async def test_type_text_in_an_untrusted_app_asks_and_respects_no(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    window = desktop.add("Spotify", "Spotify")
    desktop.controls[window.hwnd] = [Control("field", "Search")]
    h = make_app(
        [reply("", ("type_text", {"app": "spotify", "text": "lofi"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("type lofi in spotify")
    assert desktop.typed == []
    assert h.channel.requests[0].summary == 'Type "lofi" in Spotify'
    assert h.audit()[0]["decision"] == "denied"


async def test_whatsapp_typing_asks_even_when_config_trusts_it(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    window = desktop.add("WhatsApp", "WhatsApp.Root")
    desktop.controls[window.hwnd] = [Control("field", "Type a message")]
    h = make_app(
        [reply("", ("type_text", {"app": "WhatsApp", "text": "hi"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
        overrides={"safety": {"trusted_ui_apps": ["WhatsApp"]}},
    )
    await h.app.agent.run_turn("type hi in whatsapp")
    assert h.channel.requests
    assert "always asks" in (h.channel.requests[0].reason or "")
    assert desktop.typed == []


async def test_type_text_into_a_named_field(make_app: MakeApp, desktop: FakeDesktop) -> None:
    hwnd = notepad(desktop, DOC, Control("field", "Find what"))
    args = {"app": "notepad", "text": "milk", "field": "find"}
    h = make_app([reply("", ("type_text", args)), reply("Done.")])
    await h.app.agent.run_turn("type milk in the find box")
    assert desktop.typed == ["milk"]
    focused = desktop.field[hwnd]
    assert focused is not None
    assert focused.name == "Find what"


# click and press_keys


async def test_click_in_a_trusted_app(make_app: MakeApp, desktop: FakeDesktop) -> None:
    notepad(desktop)
    h = make_app([reply("", ("click", {"app": "notepad", "target": "save"})), reply("Saved.")])
    await h.app.agent.run_turn("click save in notepad")
    assert desktop.pressed == ["Save"]
    assert h.channel.requests == []


async def test_clicking_something_destructive_asks_first(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    notepad(desktop)
    h = make_app(
        [reply("", ("click", {"app": "notepad", "target": "delete all"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("click delete all")
    assert desktop.pressed == []
    assert h.channel.requests[0].summary == "Click the Delete all button in Notepad"


async def test_click_needs_the_app_to_be_open(make_app: MakeApp) -> None:
    h = make_app([reply("", ("click", {"app": "notepad", "target": "save"})), reply("Sorry.")])
    await h.app.agent.run_turn("click save")
    assert "Open it first" in (h.audit()[0]["error"] or "")


async def test_press_keys_sends_the_shortcut(make_app: MakeApp, desktop: FakeDesktop) -> None:
    notepad(desktop)
    h = make_app([reply("", ("press_keys", {"app": "notepad", "keys": "ctrl+s"})), reply("Done.")])
    await h.app.agent.run_turn("press ctrl s in notepad")
    assert desktop.keys == [((0x11,), ord("S"))]
    assert h.channel.requests == []


async def test_closing_keys_ask_first(make_app: MakeApp, desktop: FakeDesktop) -> None:
    notepad(desktop)
    h = make_app(
        [reply("", ("press_keys", {"app": "notepad", "keys": "alt+f4"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("press alt f4")
    assert desktop.keys == []
    assert h.audit()[0]["decision"] == "denied"


# read_window_text


async def test_read_window_text_returns_text_and_controls_as_untrusted_data(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    notepad(desktop)
    h = make_app([reply("", ("read_window_text", {"app": "notepad"})), reply("Milk.")])
    result = await h.app.agent.run_turn("what does notepad say")
    data = result.outcomes[0].result.data
    assert data["text"] == "Shopping list\nmilk"
    assert data["controls"] == ["Text editor document", "Save button", "Delete all button"]
    tool_message = next(m for m in h.llm.requests[1] if m["role"] == "tool")
    assert 'untrusted="true"' in tool_message["content"]


async def test_reading_the_registry_editor_is_blocked(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    desktop.add("Registry Editor", "regedit")
    h = make_app([reply("", ("read_window_text", {"app": "registry editor"})), reply("No.")])
    await h.app.agent.run_turn("read the registry editor")
    assert h.audit()[0]["decision"] == "blocked"


async def test_type_text_says_so_when_the_app_dropped_characters(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    notepad(desktop)
    desktop.app_text = "hello ddddd"
    h = make_app(
        [reply("", ("type_text", {"app": "notepad", "text": "hello world"})), reply("Hm.")]
    )
    result = await h.app.agent.run_turn("type hello world in notepad")
    outcome = result.outcomes[0].result
    assert outcome.data["matches"] is False
    assert "dropped some characters" in (outcome.speech or "")


async def test_type_text_cannot_check_apps_that_hide_their_text(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    notepad(desktop)
    desktop.app_text = ""
    h = make_app([reply("", ("type_text", {"app": "notepad", "text": "hi"})), reply("Done.")])
    result = await h.app.agent.run_turn("type hi in notepad")
    assert result.outcomes[0].result.data["checked"] is False
