"""focus_app, close_app, the persistent app index, window matching, open_url, and vscode_open."""

from __future__ import annotations

import json
import subprocess
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.storage.db import Database
from jarvis.tools.apps import index as app_index
from jarvis.tools.apps.index import AppEntry, AppIndex, AppStore, looks_unsaved, title_parts
from jarvis.tools.apps.tools import app_windows
from jarvis.tools.base import ToolContext
from tests.conftest import FakeChannel, FakeDesktop, MakeApp, reply


async def test_focus_app_switches_to_an_open_window(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    desktop.add("Untitled - Notepad", "Notepad")
    code = desktop.add("main.py - JARVIS - Visual Studio Code", "Code")
    h = make_app([reply("", ("focus_app", {"name": "vs code"})), reply("Done.")])
    await h.app.agent.run_turn("switch to vs code")
    assert desktop.focused == [code.hwnd]
    assert h.audit()[0]["decision"] == "auto"


async def test_focus_app_opens_the_app_when_not_running(
    make_app: MakeApp, desktop: FakeDesktop, launched: list
) -> None:
    h = make_app([reply("", ("focus_app", {"name": "calculator"})), reply("Opening it.")])
    await h.app.agent.run_turn("go to calculator")
    assert [entry.name for entry in launched] == ["Calculator"]
    assert desktop.focused == []


async def test_close_safe_app_without_asking(make_app: MakeApp, desktop: FakeDesktop) -> None:
    calc = desktop.add("Calculator", "ApplicationFrameHost")
    h = make_app([reply("", ("close_app", {"name": "calculator"})), reply("Closed.")])
    await h.app.agent.run_turn("close the calculator")
    assert desktop.closed == [calc.hwnd]
    assert h.channel.requests == []


async def test_close_asks_first_and_flags_unsaved_work(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    desktop.add("*shopping list - Notepad", "Notepad")
    h = make_app(
        [reply("", ("close_app", {"name": "notepad"})), reply("Left it open.")],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("close notepad")
    (request,) = h.channel.requests
    assert request.summary == "Close Notepad"
    assert "Unsaved changes" in (request.reason or "")
    assert desktop.closed == []
    assert h.audit()[0]["decision"] == "denied"


async def test_close_reports_an_app_that_is_not_open(make_app: MakeApp) -> None:
    h = make_app([reply("", ("close_app", {"name": "spotify"})), reply("It isn't open.")])
    await h.app.agent.run_turn("close spotify")
    assert "does not seem to be open" in h.audit()[0]["error"]


def test_title_parts_split_on_dashes_and_bars() -> None:
    title = "Song \u2013 Artist - Spotify | Premium"
    assert title_parts(title) == ["song", "artist", "spotify", "premium"]
    assert looks_unsaved("*notes.txt - Notepad")
    assert looks_unsaved("\u25cf main.py - JARVIS - Visual Studio Code")
    assert not looks_unsaved("Untitled - Notepad")


async def test_window_matching_does_not_confuse_apps(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    notepad = desktop.add("Untitled - Notepad", "Notepad")
    h = make_app()
    ctx = ToolContext(h.app.settings, h.channel, h.app.services, "s", "t")
    assert await app_windows(ctx, None, "visual studio code") == []
    assert await app_windows(ctx, None, "notepad") == [notepad]


async def test_app_index_persists_and_refreshes_on_a_miss() -> None:
    db = Database(":memory:")
    calls: list[int] = []

    def source() -> list[AppEntry]:
        calls.append(1)
        names = ["Notepad"] if len(calls) == 1 else ["Notepad", "Figma"]
        return [AppEntry(n, f"id.{n}", "appsfolder", n) for n in names]

    first = AppIndex(sources=[source], store=AppStore(db))
    assert (await first.match("notepad")).entry is not None
    second = AppIndex(sources=[source], store=AppStore(db), max_age=timedelta(days=1))
    assert (await second.get("Notepad")) is not None
    assert len(calls) == 1  # loaded from SQLite, no rescan
    assert (await second.match("figma")).entry is not None
    assert len(calls) == 2  # a miss triggered one refresh


def test_scan_start_menu_fills_in_executables(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "apps": [
            {"Name": "Docker Desktop", "AppID": "{6D80}\\Docker\\Docker Desktop.exe"},
            {"Name": "Visual Studio Code", "AppID": "Microsoft.VisualStudioCode"},
            {"Name": "Notepad", "AppID": "Microsoft.WindowsNotepad_8wekyb3d8bbwe!App"},
        ],
        "links": [
            {"Name": "Visual Studio Code", "Path": "C:\\x\\Code.lnk", "Target": "C:\\VS\\Code.exe"},
            {"Name": "Uninstall Thing", "Path": "C:\\x\\u.lnk", "Target": "C:\\u.exe"},
        ],
    }

    def fake_run(*args: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(stdout=json.dumps(payload).encode("utf-8"))

    monkeypatch.setattr(subprocess, "run", fake_run)
    entries = {e.name: e for e in app_index.scan_start_menu() if e.kind == "appsfolder"}
    assert entries["Docker Desktop"].exe == "Docker Desktop"
    assert entries["Visual Studio Code"].exe == "Code"
    assert entries["Notepad"].exe is None
    shortcuts = [e.name for e in app_index.scan_start_menu() if e.kind == "shortcut"]
    assert shortcuts == ["Visual Studio Code"]  # uninstallers are skipped


@pytest.mark.parametrize(
    ("url", "decision", "opened"),
    [
        ("github.com", "auto", "https://github.com"),
        ("https://python.org/downloads", "auto", "https://python.org/downloads"),
        ("file:///C:/Windows/System32", "blocked", None),
        ("javascript:alert(1)", "blocked", None),
    ],
)
async def test_open_url_allows_only_web_links(
    make_app: MakeApp, desktop: FakeDesktop, url: str, decision: str, opened: str | None
) -> None:
    h = make_app([reply("", ("open_url", {"url": url})), reply("ok")])
    await h.app.agent.run_turn(f"open {url}")
    assert h.audit()[0]["decision"] == decision
    assert desktop.urls == ([opened] if opened else [])


async def test_vscode_open_jumps_to_a_line(
    make_app: MakeApp, desktop: FakeDesktop, monkeypatch: pytest.MonkeyPatch
) -> None:
    from pathlib import Path

    monkeypatch.setattr("jarvis.tools.apps.vscode.find_code_exe", lambda: Path("C:/VS/Code.exe"))
    h = make_app()
    target = h.files_root / "main.py"
    target.write_text("print('hi')\n", encoding="utf-8")
    h.llm._script = [reply("", ("vscode_open", {"path": str(target), "line": 12})), reply("ok")]
    await h.app.agent.run_turn("open main.py in vs code at line 12")
    assert desktop.spawned == [
        ["C:\\VS\\Code.exe", "--goto", f"{target}:12"]
    ] or desktop.spawned == [[str(Path("C:/VS/Code.exe")), "--goto", f"{target}:12"]]


async def test_vscode_open_outside_allowed_folders_is_blocked(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    h = make_app(
        [reply("", ("vscode_open", {"path": "C:/Windows/win.ini"})), reply("Not allowed.")]
    )
    await h.app.agent.run_turn("open win.ini in vs code")
    assert h.audit()[0]["decision"] == "blocked"
    assert desktop.spawned == []


async def test_refresh_on_miss_works_right_after_boot(monkeypatch: pytest.MonkeyPatch) -> None:
    # time.monotonic() counts from boot; a fresh machine (like a CI runner) starts near zero.
    monkeypatch.setattr(app_index.time, "monotonic", lambda: 5.0)
    db = Database(":memory:")
    AppStore(db).save([AppEntry("Notepad", "id.Notepad", "appsfolder")])
    index = AppIndex(
        sources=[lambda: [AppEntry("Figma", "id.Figma", "appsfolder")]], store=AppStore(db)
    )
    assert (await index.match("figma")).entry is not None
