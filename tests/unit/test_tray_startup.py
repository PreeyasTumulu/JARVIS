"""The tray icon and starting at login (no real tray, COM, or Startup folder in tests)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from rich.console import Console

from jarvis.cli import manage_startup
from jarvis.core.events import VoiceStateChanged
from jarvis.platform import startup
from jarvis.tray import COLORS, LABELS, Tray, icon_image
from tests.conftest import FakeDesktop


class FakeIcon:
    def __init__(self) -> None:
        self.icon: Any = None
        self.title = ""
        self.menu_updates = 0

    def update_menu(self) -> None:
        self.menu_updates += 1


def test_the_icon_color_follows_the_state() -> None:
    for state in ("idle", "listening", "muted"):
        image = icon_image(state)
        assert image.size == (64, 64)
        red, green, blue, alpha = image.getpixel((8, 32))
        assert f"#{red:02x}{green:02x}{blue:02x}" == COLORS[state]
        assert alpha == 255


async def test_tray_actions_reach_the_event_loop(desktop: FakeDesktop) -> None:
    loop = asyncio.get_running_loop()
    calls: list[Any] = []

    async def stop() -> None:
        calls.append("stop")

    async def set_muted(muted: bool) -> None:
        calls.append(("muted", muted))

    tray = Tray(
        loop=loop,
        url=lambda: "http://127.0.0.1:8765/?token=t",
        stop=stop,
        quit=lambda: calls.append("quit"),
        set_muted=set_muted,
    )
    tray._icon = FakeIcon()
    tray.on_event(VoiceStateChanged(state="listening"))
    assert tray._icon.title == f"Jarvis: {LABELS['listening']}"
    for action in (tray._on_open, tray._on_mic, tray._on_stop, tray._on_quit):
        await asyncio.to_thread(action)  # pystray calls these from its own thread
    await asyncio.sleep(0.05)
    assert desktop.urls == ["http://127.0.0.1:8765/?token=t"]
    assert calls == [("muted", True), "stop", "quit"]
    tray.show("muted")
    await asyncio.to_thread(tray._on_mic)
    await asyncio.sleep(0.05)
    assert calls[-1] == ("muted", False)


def test_without_voice_the_tray_has_no_mic(desktop: FakeDesktop) -> None:
    tray = Tray(loop=asyncio.new_event_loop(), url=lambda: None, stop=None, quit=lambda: None)  # type: ignore[arg-type]
    assert tray.state == "off"


def test_the_launcher_uses_uvw_when_it_is_there(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("shutil.which", lambda name: r"C:\uv\uvw.exe" if name == "uvw" else None)
    launch = startup.launcher(Path(r"C:\Jarvis"))
    assert launch.target == r"C:\uv\uvw.exe"
    assert launch.arguments == (
        r'run --project "C:\Jarvis" --extra voice --extra piper pythonw '
        "-m jarvis serve --tray --wake --no-browser"
    )
    monkeypatch.setattr("shutil.which", lambda name: None)
    fallback = startup.launcher(Path(r"C:\Jarvis"))
    assert fallback.target == r"C:\Jarvis\.venv\Scripts\pythonw.exe"


def test_startup_enable_status_disable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    written: dict[Path, startup.Launcher] = {}

    def write(path: Path, launch: startup.Launcher) -> None:
        path.write_text("lnk")
        written[path] = launch

    monkeypatch.setattr(startup, "write_shortcut", write)
    monkeypatch.setattr(
        startup, "read_shortcut", lambda path: written.get(path) if path.exists() else None
    )
    console = Console(record=True, width=200)
    manage_startup("enable", console, tmp_path)
    manage_startup("status", console, tmp_path)
    assert (tmp_path / "Jarvis.lnk").exists()
    manage_startup("disable", console, tmp_path)
    assert not (tmp_path / "Jarvis.lnk").exists()
    text = console.export_text()
    assert "will start at login" in text
    assert "Jarvis starts at login" in text
    assert "will no longer start" in text
