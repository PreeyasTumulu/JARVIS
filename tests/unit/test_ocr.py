"""Screen reading with OCR: finding text, the read fallback, clicks found by OCR (always
asking), and read_screen. Windows OCR and the screen are faked."""

from __future__ import annotations

from typing import Any

import pytest

from jarvis.platform import ocr
from jarvis.platform.ocr import Line, Word
from jarvis.platform.uia import Control
from tests.conftest import FakeChannel, FakeDesktop, MakeApp, reply


def line(*words: tuple[str, int, int]) -> Line:
    """Words as (text, left, top), each 50 wide and 12 high."""
    return Line(" ".join(w for w, _, _ in words), tuple(Word(w, x, y, 50, 12) for w, x, y in words))


SCREEN = [
    line(("Quarterly", 10, 10), ("report", 70, 10)),
    line(("Save", 20, 150), ("draft", 75, 150)),
    line(("Delete", 200, 150)),
]


class FakeOcr:
    def __init__(self, lines: list[Line]) -> None:
        self.lines = lines
        self.reads = 0
        self.clicks: list[tuple[int, int]] = []


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> FakeOcr:
    from jarvis.tools.ui import tools

    fake = FakeOcr(SCREEN)

    async def ocr_window(window: Any, app: str) -> list[Line]:
        fake.reads += 1
        await tools.bring_forward(window, app)  # as the real one does before reading
        return fake.lines

    async def read(rect: Any) -> list[Line]:
        fake.reads += 1
        return fake.lines

    monkeypatch.setattr(tools, "ocr_window", ocr_window)
    monkeypatch.setattr(tools.ocr, "read", read)
    monkeypatch.setattr(tools.sendinput, "click_at", lambda x, y: fake.clicks.append((x, y)))
    return fake


def canvas_app(desktop: FakeDesktop) -> int:
    """A window that shows UI Automation nothing, like a game or a drawing canvas."""
    window = desktop.add("Zeta Report Viewer", "zeta")
    desktop.controls[window.hwnd] = []
    desktop.lines[window.hwnd] = []
    return window.hwnd


# Finding text


def test_find_one_or_more_words() -> None:
    best, rival = ocr.find(SCREEN, "save draft")
    assert best is not None
    assert (best.text, best.center) == ("Save draft", (72, 156))
    assert rival is None
    assert ocr.find(SCREEN, "Delete!")[0] is not None  # punctuation and case do not matter


def test_find_tolerates_ocr_slips_but_not_other_words() -> None:
    slipped = [line(("Sav3", 20, 150), ("draft", 75, 150))]
    assert ocr.find(slipped, "save draft")[0] is not None
    assert ocr.find(SCREEN, "publish")[0] is None


def test_find_reports_a_rival_in_another_place() -> None:
    twice = [*SCREEN, line(("Delete", 200, 400))]
    best, rival = ocr.find(twice, "delete")
    assert best is not None
    assert rival is not None


# Reading


async def test_a_window_without_text_is_read_with_ocr(
    make_app: MakeApp, desktop: FakeDesktop, screen: FakeOcr
) -> None:
    canvas_app(desktop)
    h = make_app([reply("", ("read_window_text", {"app": "zeta report viewer"})), reply("ok")])
    result = await h.app.agent.run_turn("what does the zeta report viewer say")
    data = result.outcomes[0].result.data
    assert data["text"] == "Quarterly report\nSave draft\nDelete"
    assert data["read_by"].startswith("OCR")
    assert result.outcomes[0].flags.untrusted


async def test_a_window_with_text_is_not_read_with_ocr(
    make_app: MakeApp, desktop: FakeDesktop, screen: FakeOcr
) -> None:
    window = desktop.add("Untitled - Notepad", "Notepad")
    desktop.lines[window.hwnd] = ["Shopping list: milk, eggs, bread, coffee, and rice for the week"]
    h = make_app([reply("", ("read_window_text", {"app": "notepad"})), reply("ok")])
    result = await h.app.agent.run_turn("what does notepad say")
    assert "read_by" not in result.outcomes[0].result.data
    assert screen.reads == 0


async def test_read_screen(make_app: MakeApp, screen: FakeOcr) -> None:
    h = make_app([reply("", ("read_screen", {})), reply("A quarterly report.")])
    result = await h.app.agent.run_turn("what's on my screen")
    outcome = result.outcomes[0]
    assert outcome.result.data["text"].startswith("Quarterly report")
    assert outcome.flags.private
    assert outcome.flags.untrusted


# Clicking by OCR


async def test_an_ocr_click_always_asks_and_lands_on_the_text(
    make_app: MakeApp, desktop: FakeDesktop, screen: FakeOcr
) -> None:
    canvas_app(desktop)
    h = make_app(
        [reply("", ("click", {"app": "zeta report viewer", "target": "save draft"})), reply("ok")]
    )
    result = await h.app.agent.run_turn("click save draft in zeta")
    assert h.channel.requests[0].summary == (
        'Click "Save draft" in zeta report viewer (found by reading the screen)'
    )
    assert result.outcomes[0].decision.value == "confirmed"
    assert screen.clicks == [(72, 156)]


async def test_no_means_no_ocr_click(
    make_app: MakeApp, desktop: FakeDesktop, screen: FakeOcr
) -> None:
    canvas_app(desktop)
    h = make_app(
        [reply("", ("click", {"app": "zeta report viewer", "target": "delete"})), reply("ok")],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("click delete in zeta")
    assert screen.clicks == []


async def test_text_that_moved_away_is_not_clicked_blindly(
    make_app: MakeApp, desktop: FakeDesktop, screen: FakeOcr, monkeypatch: pytest.MonkeyPatch
) -> None:
    canvas_app(desktop)
    h = make_app(
        [reply("", ("click", {"app": "zeta report viewer", "target": "save draft"})), reply("ok")]
    )
    original = h.channel.confirm

    async def confirm_then_change(request: Any) -> Any:
        screen.lines = [line(("Saved", 20, 150))]  # the screen changed before the click
        return await original(request)

    monkeypatch.setattr(h.channel, "confirm", confirm_then_change)
    result = await h.app.agent.run_turn("click save draft")
    assert not result.outcomes[0].result.ok
    assert screen.clicks == []


async def test_controls_known_to_ui_automation_are_pressed_as_before(
    make_app: MakeApp, desktop: FakeDesktop, screen: FakeOcr
) -> None:
    window = desktop.add("Untitled - Notepad", "Notepad")
    desktop.controls[window.hwnd] = [Control("button", "Save")]
    h = make_app([reply("", ("click", {"app": "notepad", "target": "save"})), reply("ok")])
    await h.app.agent.run_turn("click save in notepad")
    assert desktop.pressed == ["Save"]
    assert screen.reads == 0
    assert h.channel.requests == []


async def test_ocr_clicks_can_be_turned_off(
    make_app: MakeApp, desktop: FakeDesktop, screen: FakeOcr
) -> None:
    canvas_app(desktop)
    h = make_app(
        [reply("", ("click", {"app": "zeta report viewer", "target": "save draft"})), reply("ok")],
        overrides={"ui": {"ocr_fallback": False}},
    )
    result = await h.app.agent.run_turn("click save draft")
    assert "There is no control called" in (result.outcomes[0].result.error or "")
    assert screen.clicks == []
