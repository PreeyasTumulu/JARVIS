"""Phase 26: app timing and scheduled actions, opening files by name, notes, sheets, Calculator."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytest

from jarvis.core.channel import ApprovedChannel, ConfirmationRequest
from jarvis.llm.types import ToolCall
from jarvis.tools.base import ToolContext
from jarvis.tools.notes import note_day
from jarvis.tools.office import sheets
from jarvis.tools.office.calculator import display_value, typable
from jarvis.tools.office.sheets import Written, cell_value
from jarvis.tools.system.reminders import ReminderScheduler
from tests.conftest import FakeChannel, FakeDesktop, Harness, MakeApp, _run_inline, reply

NOW = datetime(2026, 11, 7, 10, 0)


def context(h: Harness) -> ToolContext:
    app = h.app
    return ToolContext(app.settings, h.channel, app.services, "s", "t")


async def call(h: Harness, tool: str, **args: Any) -> Any:
    return await h.app.agent.executor.run(ToolCall("c1", tool, json.dumps(args)), context(h))


def at_ten(h: Harness) -> None:
    h.app.services.reminders.clock = NOW.timestamp


# Opening, with timing


async def test_opening_waits_for_the_window_and_says_how_long(make_app: MakeApp) -> None:
    h = make_app()
    outcome = await call(h, "open_app", name="notepad")
    assert outcome.result.ok
    seconds = outcome.result.data["seconds"]
    assert 0 < seconds < 2
    assert outcome.result.speech == f"Notepad is open, in {seconds:g} seconds."


async def test_an_app_that_was_already_running(
    make_app: MakeApp, desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("jarvis.tools.apps.tools.ALREADY_OPEN_S", 0.3)
    desktop.add("Spotify", "Spotify.exe")
    desktop.launch_shows_window = False  # a single-instance app just comes forward
    h = make_app(overrides={"safety": {"app_allowlist": ["Spotify"]}})
    outcome = await call(h, "open_app", name="spotify")
    assert outcome.result.speech == "Spotify was already open."


async def test_an_app_that_shows_no_window_in_time(make_app: MakeApp, desktop: FakeDesktop) -> None:
    desktop.launch_shows_window = False
    h = make_app(overrides={"apps": {"open_wait_s": 0.5}})
    outcome = await call(h, "open_app", name="notepad")
    assert outcome.result.ok
    assert "has not shown a window after 0.5 seconds" in outcome.result.speech


# Scheduled actions


async def test_close_an_app_later_asks_once_now(make_app: MakeApp, desktop: FakeDesktop) -> None:
    channel = FakeChannel(confirm=True)
    h = make_app(channel=channel)
    at_ten(h)
    outcome = await call(h, "schedule_app", action="close", name="spotify", in_minutes=20)
    assert outcome.result.ok
    assert outcome.result.speech.startswith("I'll close Spotify at 10:20 AM.")
    (request,) = channel.requests  # Spotify is not safe to close, so the yes is asked now
    assert request.summary == "Close Spotify at 10:20 AM"
    (item,) = h.app.services.reminders.pending()
    assert item.kind == "app"
    assert item.action is not None
    assert item.action["tool"] == "close_app"
    assert item.action["approved"]

    # When it falls due the gate rates it again, and the earlier yes answers its question.
    desktop.add("Spotify", "Spotify.exe")
    said = await h.app.run_scheduled(item)
    assert said == "As you asked: Closed Spotify."
    assert len(channel.requests) == 1  # not asked a second time
    row = next(r for r in h.audit() if r["tool"] == "close_app")
    assert (row["tool"], row["decision"], row["confirmed_via"], row["handled_by"]) == (
        "close_app",
        "confirmed",
        "schedule",
        "schedule",
    )


async def test_a_scheduled_safe_open_needs_no_yes(make_app: MakeApp, launched: list) -> None:
    channel = FakeChannel(confirm=False)
    h = make_app(channel=channel)
    at_ten(h)
    await call(h, "schedule_app", action="open", name="vs code", at="9 pm")
    (item,) = h.app.services.reminders.pending()
    assert item.message == "Open Visual Studio Code"
    assert item.action is not None
    assert item.action["approved"] is None
    assert channel.requests == []
    assert (await h.app.run_scheduled(item)).startswith("As you asked: Visual Studio Code is open")
    assert [entry.name for entry in launched] == ["Visual Studio Code"]


async def test_an_earlier_yes_counts_only_for_the_same_call() -> None:
    inner = FakeChannel(confirm=False)
    channel = ApprovedChannel(inner, "abc123")
    same = ConfirmationRequest("r1", "close_app", "Close Spotify", "abc123", None, 30)
    other = ConfirmationRequest("r2", "close_app", "Close Notepad", "zzz999", None, 30)
    assert await channel.confirm(same) is True
    assert await channel.confirm(other) is False  # asked on the real channel, which said no
    assert [r.request_id for r in inner.requests] == ["r2"]
    assert channel.name == "schedule"


async def test_an_action_that_fell_due_while_jarvis_was_off_is_not_run_late(
    make_app: MakeApp, launched: list
) -> None:
    h = make_app()
    at_ten(h)
    await call(h, "schedule_app", action="open", name="notepad", in_minutes=1)
    said: list[str] = []
    ran: list[Any] = []

    async def announce(text: str) -> None:
        said.append(text)

    async def run_action(item: Any) -> str:
        ran.append(item)
        return "ran"

    scheduler = ReminderScheduler(h.app.services.reminders, h.app.bus, announce, run_action)
    (item,) = h.app.services.reminders.pending()
    await scheduler._fire(item, item.due_at + 3600)
    assert ran == []
    assert said == ["I did not open Notepad at 10:01 AM: Jarvis was not running then."]
    assert h.app.services.reminders.pending() == []
    assert launched == []


async def test_scheduled_actions_are_listed_and_cancelled(make_app: MakeApp) -> None:
    h = make_app()
    at_ten(h)
    await call(h, "schedule_app", action="open", name="notepad", in_minutes=30)
    listed = await call(h, "list_reminders")
    assert listed.result.data[0]["kind"] == "scheduled action"
    assert (await call(h, "cancel_reminder", which="notepad")).result.ok
    assert h.app.services.reminders.pending() == []


# Opening a file by name, in one call


async def test_open_a_file_by_name_without_finding_it_first(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    h = make_app([reply("", ("open_file", {"path": "jarvis readme"})), reply("Opened.")])
    readme = h.files_root / "Projects" / "jarvis" / "README.md"
    readme.parent.mkdir(parents=True)
    readme.write_text("# Jarvis", "utf-8")
    await h.app.agent.run_turn("open the jarvis readme")
    assert desktop.opened_files == [str(readme)]
    assert len(h.llm.requests) == 2  # one tool call, then the answer


# Notes


@pytest.fixture
def notes_app(make_app: MakeApp, tmp_path: Path) -> Harness:
    h = make_app(overrides={"notes": {"folder": str(tmp_path / "Jarvis Notes")}})
    at_ten(h)
    return h


async def test_a_note_goes_into_today_s_file(notes_app: Harness, tmp_path: Path) -> None:
    first = await call(notes_app, "take_note", text="that the meeting moved to 5")
    await call(notes_app, "take_note", text="buy milk")
    assert first.result.speech == "Noted."
    text = (tmp_path / "Jarvis Notes" / "2026-11-07.md").read_text("utf-8")
    assert text == "# Notes, 7 November 2026\n\n- 10:00 the meeting moved to 5\n- 10:00 buy milk\n"


async def test_notes_are_read_back_as_data(notes_app: Harness) -> None:
    await call(notes_app, "take_note", text="call the bank")
    outcome = await call(notes_app, "read_notes", day="today")
    assert outcome.result.speech == "One note from today: call the bank"
    assert "untrusted" in outcome.model_content(4000).casefold() or outcome.tool.untrusted
    empty = await call(notes_app, "read_notes", day="yesterday")
    assert empty.result.speech == "You have no notes from yesterday."


async def test_lines_you_add_by_hand_are_kept(notes_app: Harness, tmp_path: Path) -> None:
    await call(notes_app, "take_note", text="groceries")
    path = tmp_path / "Jarvis Notes" / "2026-11-07.md"
    path.write_text(path.read_text("utf-8") + "  eggs and bread\n- 11:15 dentist at 4\n", "utf-8")
    outcome = await call(notes_app, "read_notes")
    assert [n["note"] for n in outcome.result.data["notes"]] == [
        "groceries eggs and bread",
        "dentist at 4",
    ]


async def test_open_notes_starts_notepad(
    notes_app: Harness, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[Path] = []
    monkeypatch.setattr("jarvis.tools.notes.spawn_notepad", opened.append)
    outcome = await call(notes_app, "open_notes")
    assert outcome.result.ok
    assert opened == [tmp_path / "Jarvis Notes" / "2026-11-07.md"]
    assert not (await call(notes_app, "open_notes", day="yesterday")).result.ok


def test_note_days() -> None:
    today = NOW.date()
    assert note_day("today", today) == today
    assert note_day("yesterday", today).day == 6
    assert note_day("monday", today).isoformat() == "2026-11-02"  # the 7th is a Saturday
    assert note_day("on friday", today).isoformat() == "2026-11-06"
    assert note_day("3 days ago", today).day == 4
    assert note_day("2026-10-01", today).month == 10


# Sheets


def test_cells_keep_numbers_as_numbers() -> None:
    assert cell_value("450") == 450
    assert cell_value("12.5") == 12.5
    assert cell_value("1,200") == 1200
    assert cell_value("2026-11-07") == "2026-11-07"
    assert cell_value(" Groceries ") == "Groceries"


@pytest.fixture
def budget(make_app: MakeApp) -> tuple[Harness, Path]:
    import openpyxl

    h = make_app()
    path = h.files_root / "Budget 2026.xlsx"
    workbook = openpyxl.Workbook()
    workbook.active.title = "Expenses"
    workbook.active.append(["Date", "Item", "Amount"])
    workbook.active.append(["2026-11-01", "Rent", 15000])
    workbook.create_sheet("Income")
    workbook.save(path)

    async def not_in_excel(*args: Any) -> None:
        return None

    return h, path


@pytest.fixture(autouse=True)
def no_excel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Tests never reach a real Excel: the COM step reports the workbook is not open."""
    monkeypatch.setattr(sheets, "_excel_write", lambda *args: None)
    monkeypatch.setattr(sheets, "run_com", _run_inline)


async def test_a_row_is_added_to_a_closed_workbook_after_a_yes(
    budget: tuple[Harness, Path],
) -> None:
    import openpyxl

    h, path = budget
    outcome = await call(
        h, "add_sheet_row", file="budget", values=["2026-11-07", "Groceries", "450"]
    )
    (request,) = h.channel.requests
    assert request.summary == "Add a row to Budget 2026.xlsx: 2026-11-07 | Groceries | 450"
    assert outcome.result.ok
    assert (
        outcome.result.speech
        == "Added to row 3 of Expenses in Budget 2026.xlsx: 2026-11-07, Groceries, 450."
    )
    rows = list(openpyxl.load_workbook(path).active.iter_rows(values_only=True))
    assert rows[-1] == ("2026-11-07", "Groceries", 450)
    backups = list((h.app.settings.data_dir / "backups" / "sheets").iterdir())
    assert len(backups) == 1  # a copy from before the write


async def test_a_named_sheet_and_a_missing_one(budget: tuple[Harness, Path]) -> None:
    h, _ = budget
    ok = await call(h, "add_sheet_row", file="budget", values=["Salary", "90000"], sheet="Income")
    assert ok.result.data["row"] == 1  # an empty sheet starts at the top
    missing = await call(h, "add_sheet_row", file="budget", values=["x"], sheet="Taxes")
    assert not missing.result.ok
    assert "Expenses, Income" in missing.result.error


async def test_no_means_the_file_is_untouched(make_app: MakeApp) -> None:
    h = make_app(channel=FakeChannel(confirm=False))
    path = h.files_root / "log.csv"
    path.write_text("a,b\n", "utf-8")
    await call(h, "add_sheet_row", file=str(path), values=["1", "2"])
    assert path.read_text("utf-8") == "a,b\n"


async def test_a_csv_gets_one_line_in_its_own_delimiter(make_app: MakeApp) -> None:
    h = make_app()
    path = h.files_root / "expenses.csv"
    path.write_text("date;item;amount\n2026-11-01;rent;15000", "utf-8")
    outcome = await call(
        h, "add_sheet_row", file="expenses", values=["2026-11-07", "milk; eggs", "120"]
    )
    assert outcome.result.ok
    rows = list(csv.reader(path.read_text("utf-8").splitlines(), delimiter=";"))
    assert rows[-1] == ["2026-11-07", "milk; eggs", "120"]
    assert len(rows) == 3


async def test_an_open_workbook_is_written_through_excel(
    budget: tuple[Harness, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    h, path = budget
    seen: list[Any] = []

    def excel(target: Path, values: list[Any], sheet: str | None) -> Written:
        seen.append((target, values, sheet))
        return Written(4, values, "excel", "Expenses")

    monkeypatch.setattr(sheets, "_excel_write", excel)
    outcome = await call(h, "add_sheet_row", file="budget", values=["Tea", "40"])
    assert seen == [(path, ["Tea", 40], None)]
    assert "It is not saved yet" in outcome.result.speech


async def test_a_workbook_locked_by_another_program_is_refused(
    budget: tuple[Harness, Path],
) -> None:
    h, path = budget
    (path.parent / f"~${path.name}").write_bytes(b"owner")
    outcome = await call(h, "add_sheet_row", file="budget", values=["x"])
    assert not outcome.result.ok
    assert "open in another program" in outcome.result.error


async def test_only_spreadsheets_and_only_allowed_folders(
    make_app: MakeApp, tmp_path: Path
) -> None:
    h = make_app()
    (h.files_root / "notes.txt").write_text("x", "utf-8")
    outside = tmp_path / "elsewhere.csv"
    outside.write_text("a\n", "utf-8")
    assert not (await call(h, "add_sheet_row", file="notes", values=["x"])).result.ok
    blocked = await call(h, "add_sheet_row", file=str(outside), values=["x"])
    assert not blocked.result.ok
    assert outside.read_text("utf-8") == "a\n"


# Calculator


def test_what_calculator_can_be_typed() -> None:
    assert typable("18 / 100 * 2400") == "18/100*2400"
    assert typable("(2+3)*4") == "(2+3)*4"
    for refused in ("2**10", "sqrt(9)", "15%", "import os"):
        with pytest.raises(Exception, match="Calculator"):
            typable(refused)


def test_reading_calculator_s_display() -> None:
    assert display_value(["Calculator", "Display is 432"]) == 432
    assert display_value(["Display is 1,234.5"]) == 1234.5
    assert display_value([f"Display is {chr(0x2212)}7"]) == -7
    assert display_value(["Memory"]) is None


@pytest.fixture
def calculator(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.tools.office.calculator.run_com", _run_inline)
    monkeypatch.setattr("jarvis.tools.office.calculator.SETTLE_S", 0)


async def test_the_sum_is_typed_and_checked(
    make_app: MakeApp, desktop: FakeDesktop, calculator: None
) -> None:
    window = desktop.add("Calculator", "CalculatorApp.exe")
    desktop.lines[window.hwnd] = ["Calculator", "Display is 432"]
    h = make_app()
    outcome = await call(h, "calculator_show", expression="18 / 100 * 2400")
    assert outcome.result.speech == "It's 432, and Calculator shows the same."
    assert desktop.typed == ["18/100*2400"]
    assert [vk for _, vk in desktop.keys] == [0x32, 0x1B, 0x0D]  # Alt+2, Escape, Enter
    assert desktop.keys[0][0] == (0x12,)


async def test_a_different_display_is_reported(
    make_app: MakeApp, desktop: FakeDesktop, calculator: None
) -> None:
    window = desktop.add("Calculator", "CalculatorApp.exe")
    desktop.lines[window.hwnd] = ["Display is 20"]
    h = make_app()
    outcome = await call(h, "calculator_show", expression="2+3*4")
    assert outcome.result.speech == "Calculator shows 20, but I get 14. Check what was typed."


async def test_calculator_is_started_when_it_is_closed(
    make_app: MakeApp, desktop: FakeDesktop, calculator: None, launched: list
) -> None:
    h = make_app()
    outcome = await call(h, "calculator_show", expression="6*7")
    assert [entry.name for entry in launched] == ["Calculator"]
    assert outcome.result.ok
    assert "couldn't read its display" in outcome.result.speech  # the fake window has no text


async def test_a_sheet_made_after_the_index_was_built_is_found(make_app: MakeApp) -> None:
    # The live test made log.csv after the first search had built the index.
    h = make_app()
    await h.app.services.files.search("anything")  # builds the index
    path = h.files_root / "log.csv"
    path.write_text("when;what\n", "utf-8")
    outcome = await call(h, "add_sheet_row", file="log", values=["10:00", "tea"])
    assert outcome.result.ok
    assert path.read_text("utf-8").splitlines()[-1] == "10:00;tea"


def test_dates_excel_made_are_read_back_plainly() -> None:
    # Live: Excel turned "2026-11-07" into a date with a time zone.
    from datetime import UTC
    from datetime import datetime as dt

    from jarvis.tools.office.sheets import plain

    assert plain(dt(2026, 11, 7, tzinfo=UTC)) == "2026-11-07"
    assert plain(dt(2026, 11, 7, 9, 30)) == "2026-11-07 09:30"
    assert plain(40.0) == 40.0


# Found by the live run with the real model


async def test_note_that_is_answered_without_the_model(notes_app: Harness) -> None:
    result = await notes_app.app.agent.run_turn("Note that the plumber comes on Tuesday.")
    assert result.handled_by == "template"
    assert result.text == "Noted."
    assert notes_app.llm.requests == []
    (read,) = [o for o in result.outcomes]
    assert read.args == {"text": "the plumber comes on Tuesday."}


@pytest.mark.parametrize(
    "said",
    ["notepad please", "notes", "note", "what did I note today", "open my notes"],
)
async def test_other_note_words_still_go_to_the_model(notes_app: Harness, said: str) -> None:
    from jarvis.core.pipeline import RouteRequest, template

    request = RouteRequest(said, notes_app.app.registry, notes_app.app.services)
    assert await template(request) is None


async def test_a_relative_time_in_at_is_understood(make_app: MakeApp) -> None:
    h = make_app()
    at_ten(h)
    outcome = await call(h, "schedule_app", action="open", name="notepad", at="in 20 minutes")
    assert outcome.result.ok
    assert "10:20 AM" in outcome.result.speech


async def test_a_sheet_name_that_is_part_of_the_file_name_is_ignored(
    budget: tuple[Harness, Path],
) -> None:
    h, _ = budget
    outcome = await call(h, "add_sheet_row", file="budget", values=["Tea", "40"], sheet="2026")
    assert outcome.result.ok
    assert outcome.result.data["row"] == 3  # the first sheet, not a sheet called 2026
