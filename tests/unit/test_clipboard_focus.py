"""Clipboard history and focus sessions, with the clipboard, Windows, and the clock faked."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest

from jarvis.config import ClipboardSettings
from jarvis.core.fast_path import fast_call
from jarvis.core.tool_routing import select_tools
from jarvis.platform import clipboard as platform_clipboard
from jarvis.platform.notifications import NotificationAccessError, RawNotification
from jarvis.tools.catalog import build_registry
from jarvis.tools.system.clipboard import ClipboardHistory
from jarvis.tools.system.focus import Focus
from jarvis.tools.system.reminders import ReminderScheduler
from tests.conftest import MakeApp
from tests.unit.test_recall_briefing import call
from tests.unit.test_voice_session import until


class FakeBoard:
    def __init__(self) -> None:
        self.number = 1
        self.text: str | None = "there before Jarvis"
        self.locked: bool | OSError = False
        self.reads = 0

    def copy(self, text: str | None) -> None:
        self.number += 1
        self.text = text

    def read(self) -> str | None:
        self.reads += 1
        return self.text

    def is_locked(self) -> bool:
        if isinstance(self.locked, OSError):
            raise self.locked
        return self.locked

    def history(self, **settings: Any) -> ClipboardHistory:
        return ClipboardHistory(
            ClipboardSettings(history=True, **settings),
            sequence=lambda: self.number,
            read=self.read,
            locked=self.is_locked,
        )


@pytest.fixture
def board() -> FakeBoard:
    return FakeBoard()


def test_history_keeps_what_was_copied_newest_first(board: FakeBoard) -> None:
    history = board.history()
    for text in ("one", "two", "three"):
        board.copy(text)
        history.check()
    assert list(history.items) == ["three", "two", "one"]


def test_what_was_copied_before_jarvis_started_is_not_kept(board: FakeBoard) -> None:
    history = board.history()
    history.check()
    assert not history.items


def test_the_clipboard_is_only_opened_when_it_changed(board: FakeBoard) -> None:
    history = board.history()
    for _ in range(5):
        history.check()
    assert board.reads == 0


@pytest.mark.parametrize(
    "text",
    [None, "   ", "x" * 101, "sk-ant-abcdefghijklmnopqrstuvwxyz", "password = hunter2hunter2"],
)
def test_empty_long_and_secret_looking_copies_are_left_out(board: FakeBoard, text: Any) -> None:
    history = board.history(max_chars=100)
    board.copy(text)
    history.check()
    assert not history.items


def test_copying_something_again_moves_it_to_the_front(board: FakeBoard) -> None:
    history = board.history()
    for text in ("one", "two", "one"):
        board.copy(text)
        history.check()
    assert list(history.items) == ["one", "two"]


def test_only_the_newest_are_kept(board: FakeBoard) -> None:
    history = board.history(max_items=2)
    for text in ("one", "two", "three"):
        board.copy(text)
        history.check()
    assert list(history.items) == ["three", "two"]


def test_locking_empties_it_and_copies_while_locked_are_not_kept(board: FakeBoard) -> None:
    history = board.history()
    board.copy("before")
    history.check()
    board.locked = True
    board.copy("while locked")
    history.check()
    assert not history.items
    board.locked = False
    history.check()
    assert not history.items


def test_an_unknown_lock_state_counts_as_locked(board: FakeBoard) -> None:
    history = board.history()
    board.copy("kept")
    history.check()
    board.locked = OSError("no answer")
    board.copy("not kept")
    history.check()
    assert not history.items


async def test_tools_list_restore_and_forget(
    make_app: MakeApp, board: FakeBoard, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = make_app()
    history = board.history()
    h.app.services.clipboard = history
    for text in ("first", "second"):
        board.copy(text)
        history.check()
    written: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        platform_clipboard,
        "set_text",
        lambda text, *, private=False: written.append((text, private)),
    )

    listed = await call(h, "clipboard_history")
    assert [item["text"] for item in listed.result.data] == ["second", "first"]

    restored = await call(h, "clipboard_restore", position=2)
    assert restored.result.ok
    assert written == [("first", True)]  # private: it must not come back as a new copy

    assert not (await call(h, "clipboard_restore", position=3)).result.ok

    assert (await call(h, "clipboard_forget")).result.ok
    assert not history.items


async def test_tools_say_how_to_turn_it_on(make_app: MakeApp) -> None:
    h = make_app()
    outcome = await call(h, "clipboard_history")
    assert "history = true" in str(outcome.result.error)


def test_the_history_is_off_by_default(make_app: MakeApp) -> None:
    h = make_app()
    assert h.app.settings.clipboard.history is False
    assert h.app.services.clipboard is None


@pytest.mark.parametrize(
    "text", ["what did I copy earlier", "clear my clipboard history", "paste the second last thing"]
)
def test_clipboard_words_offer_the_clipboard_tools(text: str) -> None:
    names = {tool.name for tool in select_tools(text, build_registry())}
    assert {"clipboard_history", "clipboard_restore", "clipboard_forget"} <= names
    assert "forget_history" not in names


# Focus sessions


class Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 11, 2, 10, 0, tzinfo=UTC).timestamp()

    def __call__(self) -> float:
        return self.now


def focus_with_clock(h: Any) -> tuple[Focus, Clock]:
    clock = Clock()
    h.app.services.reminders.clock = clock
    focus = Focus(
        h.app.services.reminders, h.app.services.notifications, h.app.services.prefs, clock
    )
    h.app.services.focus = focus
    return focus, clock


def _message(title: str, moment: datetime, win_id: int = 1) -> RawNotification:
    return RawNotification(
        win_id=win_id, app_id="wa", app="WhatsApp", title=title, body="the words", created=moment
    )


async def test_a_session_holds_reminders_and_timers_still_ring(make_app: MakeApp) -> None:
    h = make_app()
    focus, clock = focus_with_clock(h)
    reminders = h.app.services.reminders
    said: list[str] = []

    async def announce(text: str) -> None:
        said.append(text)

    scheduler = asyncio.create_task(ReminderScheduler(reminders, h.app.bus, announce).run())
    try:
        focus.start(25)
        reminders.add("reminder", "stretch", clock.now - 1)
        reminders.add("timer", "pasta", clock.now - 1)
        await until(lambda: said == ["Timer done: pasta."])
        assert [r.message for r in reminders.pending()] == ["stretch"]

        clock.now += 300
        summary = await focus.finish()
        assert "1 reminder waited" in summary
        await until(lambda: len(said) == 2)
        assert "stretch" in said[1]
        assert "missed" in said[1]
    finally:
        scheduler.cancel()
        await asyncio.gather(scheduler, return_exceptions=True)


async def test_the_summary_gives_senders_and_never_the_words(
    make_app: MakeApp, notification_center: Any
) -> None:
    h = make_app()
    focus, clock = focus_with_clock(h)
    focus.start(25)
    moment = datetime.fromtimestamp(clock.now + 60, UTC)
    h.app.services.notifications.store.add(
        [_message("Mom", moment), _message("Ravi", moment, 2)], moment
    )
    clock.now += 25 * 60
    summary = await focus.finish()
    assert "25 minutes" in summary
    assert "2 new messages" in summary
    assert "Mom" in summary
    assert "Ravi" in summary
    assert "the words" not in summary
    assert focus.session is None


async def test_messages_from_before_the_session_do_not_count(
    make_app: MakeApp, notification_center: Any
) -> None:
    h = make_app()
    focus, clock = focus_with_clock(h)
    moment = datetime.fromtimestamp(clock.now - 600, UTC)
    h.app.services.notifications.store.add([_message("Old", moment)], moment)
    focus.start(25)
    assert "message" not in await focus.finish()


async def test_no_notification_access_still_ends_the_session(
    make_app: MakeApp, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = make_app()
    focus, _ = focus_with_clock(h)
    focus.start(25)

    async def denied() -> list[Any]:
        raise NotificationAccessError("no access")

    monkeypatch.setattr(h.app.services.notifications, "refresh", denied)
    assert "over" in await focus.finish()
    assert focus.session is None


async def test_it_ends_itself_and_says_so(make_app: MakeApp) -> None:
    h = make_app()
    focus, clock = focus_with_clock(h)
    said: list[str] = []

    async def announce(text: str) -> None:
        said.append(text)

    focus.start(25)
    clock.now += 26 * 60
    runner = asyncio.create_task(focus.run(announce))
    try:
        await until(lambda: len(said) == 1)
        assert "over, after 25 minutes" in said[0]
        assert h.app.services.reminders.quiet is False
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)


async def test_a_restart_keeps_the_session_and_its_quiet(make_app: MakeApp) -> None:
    h = make_app()
    focus, clock = focus_with_clock(h)
    focus.start(25, "report")
    h.app.services.reminders.quiet = False  # a fresh process starts loud

    again = Focus(
        h.app.services.reminders, h.app.services.notifications, h.app.services.prefs, clock
    )
    assert again.session is not None
    assert again.session.label == "report"
    assert h.app.services.reminders.quiet is True


async def test_tools(make_app: MakeApp) -> None:
    h = make_app()
    _, clock = focus_with_clock(h)
    assert (await call(h, "focus_status")).result.data == {"running": False}
    assert not (await call(h, "focus_end")).result.ok
    assert not (await call(h, "focus_start", minutes=0)).result.ok
    assert not (await call(h, "focus_start", minutes=1000)).result.ok

    started = await call(h, "focus_start", minutes=50)
    assert "50 minutes" in str(started.result.speech)
    assert "already running" in str((await call(h, "focus_start")).result.error)

    clock.now += 600
    assert (await call(h, "focus_status")).result.data["seconds_left"] == 2400
    ended = await call(h, "focus_end")
    assert "10 minutes" in str(ended.result.speech)


@pytest.mark.parametrize(
    "text",
    ["start a 50 minute focus session", "how long is left in my focus session", "pomodoro please"],
)
def test_focus_words_offer_the_session_not_focus_app(text: str) -> None:
    names = {tool.name for tool in select_tools(text, build_registry())}
    assert {"focus_start", "focus_end", "focus_status"} <= names
    assert "focus_app" not in names


def test_focusing_an_app_still_offers_focus_app() -> None:
    names = {tool.name for tool in select_tools("focus on vs code", build_registry())}
    assert "focus_app" in names
    assert "focus_start" not in names


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("start a focus session", "focus_start"),
        ("hey jarvis start focus mode", "focus_start"),
        ("end my focus session", "focus_end"),
        ("stop focus mode please", "focus_end"),
    ],
)
def test_exact_phrases_need_no_model(text: str, name: str) -> None:
    assert fast_call(text) == (name, "{}")
