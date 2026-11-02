"""focused_text: WebView2 apps report a host pane as focused, with the real field inside it."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from jarvis.platform import uia

PANE, EDIT = 50033, 50004
HWND = 42
focused_text = uia.focused_text  # the real one: conftest replaces it for every test


def element(kind: int, value: str = "") -> Any:
    return SimpleNamespace(CachedControlType=kind, value=value)


class Found:
    def __init__(self, items: list[Any]) -> None:
        self.items = items
        self.Length = len(items)

    def GetElement(self, index: int) -> Any:
        return self.items[index]


@pytest.fixture
def window(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A scripted UIA client: what has the focus, and what is focused inside the window."""
    state: dict[str, Any] = {"focused": element(PANE), "inside": [], "top": HWND, "refuse": False}

    def find_all(_scope: Any, _condition: Any, _cache: Any) -> Found:
        if state["refuse"]:
            raise OSError("the app is busy")
        return Found(state["inside"])

    client = SimpleNamespace(
        GetFocusedElement=lambda: SimpleNamespace(BuildUpdatedCache=lambda _c: state["focused"]),
        CreatePropertyCondition=lambda _prop, _value: "condition",
        ElementFromHandle=lambda _hwnd: SimpleNamespace(FindAllBuildCache=find_all),
    )
    lib = SimpleNamespace(UIA_HasKeyboardFocusPropertyId=1, TreeScope_Descendants=4)
    monkeypatch.setattr(uia, "_get", lambda: SimpleNamespace(client=client, lib=lib, cache="cache"))
    monkeypatch.setattr(uia, "_top_window", lambda _e: state["top"])
    monkeypatch.setattr(
        uia,
        "_cached",
        lambda e, prop: e.value if prop == "ValueValue" else False,
    )
    return state


def test_reads_the_field_focused_inside_a_web_view(window: dict[str, Any]) -> None:
    window["inside"] = [element(PANE), element(EDIT, "hello")]
    assert focused_text(HWND) == "hello"


def test_a_directly_focused_field_is_read_without_searching(window: dict[str, Any]) -> None:
    window["focused"] = element(EDIT, "typed")
    window["refuse"] = True
    assert focused_text(HWND) == "typed"


def test_a_pane_with_no_field_inside_has_no_text(window: dict[str, Any]) -> None:
    window["inside"] = [element(PANE)]
    assert focused_text(HWND) == ""


def test_a_busy_app_reads_as_no_text_instead_of_failing(window: dict[str, Any]) -> None:
    window["refuse"] = True
    assert focused_text(HWND) == ""


def test_focus_in_another_window_is_not_read(window: dict[str, Any]) -> None:
    window["top"] = 7
    window["inside"] = [element(EDIT, "hello")]
    assert focused_text(HWND) is None
