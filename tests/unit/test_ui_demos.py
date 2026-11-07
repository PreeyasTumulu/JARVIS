"""Phase 30: the UI demos stay standalone, offline, and in step with their shared kit (ADR-100)."""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
DEMOS = ROOT / "ui-demos"
_spec = importlib.util.spec_from_file_location(
    "build_ui_demos", ROOT / "scripts" / "build_ui_demos.py"
)
assert _spec is not None
assert _spec.loader is not None
build = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(build)

PAGES = build.pages()
STATES = ("idle", "listening", "thinking", "speaking", "confirm", "tool", "error")


def test_there_are_six_concepts_and_the_chat() -> None:
    assert [p.stem for p in PAGES] == [
        "chat",
        "constellation",
        "edge",
        "orb",
        "pill",
        "reactor",
        "terminal",
    ]


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_each_page_carries_the_current_kit(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    assert build.with_kit(html, build.kit()) == html, "run scripts/build_ui_demos.py"


@pytest.mark.parametrize("page", [*PAGES, DEMOS / "index.html"], ids=lambda p: p.stem)
def test_pages_make_no_network_requests(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    assert not re.search(r"""(src|href)\s*=\s*["']?(https?:)?//""", html, re.I)
    assert "<script src" not in html
    for call in ("fetch(", "XMLHttpRequest", "sendBeacon", "@import"):
        assert call not in html, call
    # Only the chat opens a socket, only when jarvis serve served it, and only to this computer.
    sockets = re.findall(r"new WebSocket\((`[^`]*`|[^)]*)\)", html)
    if page.stem == "chat":
        assert sockets == [
            "`ws://127.0.0.1:${LIVE.port}/ws?token=${encodeURIComponent(LIVE.token)}`"
        ]
    else:
        assert sockets == []


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_each_page_shows_every_state_and_can_answer(page: Path) -> None:
    html = page.read_text(encoding="utf-8")
    assert '<nav id="dock">' in html
    assert 'data-kit="label"' in html
    assert 'data-kit-answer="yes"' in html or "Kit.answer(" in html
    assert 'name="viewport"' in html
    assert "<title>Jarvis " in html


def test_the_kit_has_the_seven_states_and_respects_reduced_motion() -> None:
    kit = build.kit()
    listed = re.search(r"const STATES = \[(.*?)\];", kit)
    assert listed is not None
    assert tuple(re.findall(r'"(\w+)"', listed[1])) == STATES
    assert "prefers-reduced-motion" in kit
    assert "getUserMedia" in kit  # only after the button, see toggleMic


@pytest.mark.parametrize("page", PAGES, ids=lambda p: p.stem)
def test_screenshots_exist_for_the_readme(page: Path) -> None:
    for state in ("listening", "thinking", "confirm", "speaking"):
        assert (DEMOS / "screenshots" / f"{page.stem}-{state}.jpg").is_file()


def test_no_long_dashes_in_the_demos() -> None:
    for path in [*DEMOS.glob("*.html"), DEMOS / "_kit.js", *DEMOS.glob("*.md")]:
        text = path.read_text(encoding="utf-8")
        assert chr(0x2013) not in text, path.name  # en dash
        assert chr(0x2014) not in text, path.name  # em dash


def test_the_chat_waits_for_you_and_keeps_both_themes() -> None:
    html = (DEMOS / "chat.html").read_text(encoding="utf-8")
    assert 'data-kit-autoplay="off"' in html  # no run starts by itself in a chat
    assert "prefers-color-scheme: dark" in html
    assert ':root[data-theme="dark"]' in html
    assert "localStorage" in html
    assert "try {" in html
