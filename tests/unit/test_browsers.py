"""Picking the browser Jarvis drives (no registry or real browser in tests)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from jarvis.platform import browsers


class FakeKey:
    def __enter__(self) -> FakeKey:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def fake_registry(monkeypatch: pytest.MonkeyPatch, prog_id: str | None) -> None:
    def open_key(hive: Any, path: str) -> FakeKey:
        if prog_id is None or path != browsers.USER_CHOICE:
            raise OSError("missing")
        return FakeKey()

    monkeypatch.setattr(browsers.winreg, "OpenKey", open_key)
    monkeypatch.setattr(browsers.winreg, "QueryValueEx", lambda key, name: (prog_id, 1))


@pytest.mark.parametrize(
    ("prog_id", "expected"),
    [
        ("BraveHTML", "brave"),
        ("ChromeHTML", "chrome"),
        ("MSEdgeHTM", "msedge"),
        ("FirefoxURL-1", None),
    ],
)
def test_the_default_browser_is_read_from_the_https_handler(
    monkeypatch: pytest.MonkeyPatch, prog_id: str, expected: str | None
) -> None:
    fake_registry(monkeypatch, prog_id)
    assert browsers.default_browser() == expected


def test_auto_follows_a_brave_default(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    exe = tmp_path / browsers.BRAVE_RELATIVE
    exe.parent.mkdir(parents=True)
    exe.write_bytes(b"")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    fake_registry(monkeypatch, "BraveHTML")
    choice = browsers.resolve_browser("auto")
    assert choice == browsers.BrowserChoice("brave", None, exe)


def test_auto_falls_back_to_edge(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_registry(monkeypatch, "FirefoxURL-1")
    assert browsers.resolve_browser("auto") == browsers.BrowserChoice("msedge", "msedge")
    fake_registry(monkeypatch, "BraveHTML")
    monkeypatch.setattr(browsers, "find_brave", lambda: None)  # default is Brave, but it is gone
    assert browsers.resolve_browser("auto").name == "msedge"


def test_brave_that_is_missing_says_how_to_fix_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(browsers, "find_brave", lambda: None)
    with pytest.raises(FileNotFoundError, match="executable"):
        browsers.resolve_browser("brave")


def test_an_explicit_executable_wins() -> None:
    choice = browsers.resolve_browser("msedge", r"C:\Tools\vivaldi.exe")
    assert choice.executable == Path(r"C:\Tools\vivaldi.exe")
    assert choice.channel is None
