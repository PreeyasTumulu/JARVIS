"""Windows UI Automation (UIA): read a window's text and controls, press a control, focus a field.

Every function here is synchronous and must run on the COM thread (platform/com.py). UIA is used
through comtypes directly: one cross-process call (FindAllBuildCache) returns every control with
the properties we need, so reading a window takes tens of milliseconds instead of seconds.

Controls are found again by (kind, name, occurrence) rather than kept between calls, because a
cached element can belong to a window that has changed since (see `find_control`).
"""

from __future__ import annotations

import contextlib
import ctypes
import logging
from dataclasses import dataclass
from typing import Any

from jarvis.platform import sendinput

log = logging.getLogger(__name__)

MAX_ELEMENTS = 3000
MAX_PARENT_STEPS = 60

# UIA control type ids (UIAutomationClient.h) and the word the model and the user see.
KINDS: dict[int, str] = {
    50000: "button",
    50002: "check box",
    50003: "combo box",
    50004: "field",
    50005: "link",
    50007: "list item",
    50011: "menu item",
    50013: "radio button",
    50019: "tab",
    50024: "tree item",
    50029: "item",
    50030: "document",
    50031: "button",  # split button
}
TEXT_KIND = 50020
EDITABLE_KINDS = {50004, 50030}  # edit, document
TYPABLE_KINDS = EDITABLE_KINDS | {50003}  # an editable combo box takes typing too

# Pattern ids, tried in this order to press a control without moving the mouse.
INVOKE, SELECTION_ITEM, EXPAND_COLLAPSE, TOGGLE, TEXT = 10000, 10010, 10005, 10015, 10014


class UIAError(Exception):
    """A window or control could not be used. The message is meant for the user."""


@dataclass(frozen=True)
class Control:
    kind: str
    name: str
    occurrence: int = 0  # earlier controls with the same kind and name, to find this one again
    automation_id: str = ""
    enabled: bool = True
    password: bool = False

    @property
    def label(self) -> str:
        return f"{self.name} {self.kind}".strip() if self.name else self.kind


@dataclass(frozen=True)
class WindowContent:
    lines: list[str]  # visible text, top to bottom as the app lists it
    controls: list[Control]  # what can be clicked or typed into


class _Uia:
    """The UIA client object and the cache request, created once on the COM thread."""

    def __init__(self) -> None:
        import comtypes
        import comtypes.client

        _dpi_aware()
        self.lib: Any = comtypes.client.GetModule("UIAutomationCore.dll")
        lib = self.lib
        self.client: Any = comtypes.CoCreateInstance(
            lib.CUIAutomation._reg_clsid_,
            interface=lib.IUIAutomation,
            clsctx=comtypes.CLSCTX_INPROC_SERVER,
        )
        self.cache: Any = self.client.CreateCacheRequest()
        for prop in (
            lib.UIA_NamePropertyId,
            lib.UIA_ControlTypePropertyId,
            lib.UIA_AutomationIdPropertyId,
            lib.UIA_IsEnabledPropertyId,
            lib.UIA_IsOffscreenPropertyId,
            lib.UIA_IsPasswordPropertyId,
            lib.UIA_HasKeyboardFocusPropertyId,
            lib.UIA_ValueValuePropertyId,
            lib.UIA_ValueIsReadOnlyPropertyId,
            lib.UIA_IsValuePatternAvailablePropertyId,
            lib.UIA_IsTextPatternAvailablePropertyId,
            lib.UIA_BoundingRectanglePropertyId,
        ):
            self.cache.AddProperty(prop)


_uia: _Uia | None = None


def _get() -> _Uia:
    global _uia
    if _uia is None:
        _uia = _Uia()
    return _uia


def _dpi_aware() -> None:
    """Element rectangles are in physical pixels; mouse clicks must be too.

    The call fails quietly when awareness is already set (mss sets it too) and is missing before
    Windows 10 1703; either way is harmless.
    """
    with contextlib.suppress(AttributeError):
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))  # per monitor v2


def _elements(hwnd: int) -> list[Any]:
    uia = _get()
    try:
        root = uia.client.ElementFromHandle(hwnd)
        found = root.FindAllBuildCache(
            uia.lib.TreeScope_Descendants, uia.client.ControlViewCondition, uia.cache
        )
    except Exception as exc:  # comtypes raises COMError for a window that went away
        raise UIAError("That window is no longer there.") from exc
    if not found:
        return []
    return [found.GetElement(i) for i in range(min(found.Length, MAX_ELEMENTS))]


def _cached(element: Any, prop: str) -> Any:
    uia = _get()
    return element.GetCachedPropertyValue(getattr(uia.lib, f"UIA_{prop}PropertyId"))


def _control(element: Any, occurrence: int) -> Control:
    return Control(
        kind=KINDS.get(element.CachedControlType, "control"),
        name=(element.CachedName or "").strip(),
        occurrence=occurrence,
        automation_id=element.CachedAutomationId or "",
        enabled=bool(element.CachedIsEnabled),
        password=bool(element.CachedIsPassword),
    )


def _walk(hwnd: int, visible_only: bool = True) -> list[tuple[Any, Control | None, str | None]]:
    """Each element with its Control (if it can be used) and its text (if it has any).

    Elements scrolled out of view are skipped, except in a minimized window, where UIA reports
    everything as off screen.
    """
    seen: dict[tuple[str, str], int] = {}
    out: list[tuple[Any, Control | None, str | None]] = []
    for element in _elements(hwnd):
        if visible_only and element.CachedIsOffscreen:
            continue
        kind = element.CachedControlType
        control: Control | None = None
        if kind in KINDS:
            probe = _control(element, 0)
            if probe.name or kind in TYPABLE_KINDS:
                key = (probe.kind, probe.name.casefold())
                control = _control(element, seen.get(key, 0))
                seen[key] = control.occurrence + 1
        out.append((element, control, _text_of(element, kind)))
    return out


def _text_of(element: Any, kind: int) -> str | None:
    if kind == TEXT_KIND:
        return (element.CachedName or "").strip() or None
    if kind in EDITABLE_KINDS and not element.CachedIsPassword:
        value = _cached(element, "ValueValue")
        if isinstance(value, str) and value.strip():
            return value.strip()
        if _cached(element, "IsTextPatternAvailable"):
            return _document_text(element)
    return None


def _document_text(element: Any, limit: int = 20000) -> str | None:
    uia = _get()
    try:
        pattern = element.GetCurrentPattern(TEXT)
        text_pattern = pattern.QueryInterface(uia.lib.IUIAutomationTextPattern)
        text = text_pattern.DocumentRange.GetText(limit)
    except Exception:
        return None
    return text.strip() or None if isinstance(text, str) else None


def read_window(hwnd: int, max_chars: int, visible_only: bool = True) -> tuple[WindowContent, bool]:
    """Visible text and usable controls. The bool says whether the text was cut off."""
    lines: list[str] = []
    controls: list[Control] = []
    total, truncated = 0, False
    for _element, control, text in _walk(hwnd, visible_only):
        if control is not None:
            controls.append(control)
        if text and not truncated and (not lines or lines[-1] != text):
            if total + len(text) > max_chars:
                text, truncated = text[: max(0, max_chars - total)], True
            lines.append(text)
            total += len(text)
    return WindowContent(lines=[line for line in lines if line], controls=controls), truncated


def find_control(hwnd: int, wanted: Control) -> Any:
    """The live element for a control seen earlier, or UIAError if it is gone."""
    for element, control, _text in _walk(hwnd):
        if (
            control is not None
            and control.kind == wanted.kind
            and control.name.casefold() == wanted.name.casefold()
            and control.occurrence == wanted.occurrence
        ):
            return element
    raise UIAError(f"The {wanted.label} is no longer in that window.")


def press(hwnd: int, wanted: Control) -> str:
    """Press a control the way the app expects, falling back to a mouse click. Returns how."""
    uia = _get()
    element = find_control(hwnd, wanted)
    if not element.CachedIsEnabled:
        raise UIAError(f"The {wanted.label} is greyed out.")
    lib = uia.lib
    attempts = (
        (INVOKE, lib.IUIAutomationInvokePattern, "Invoke", "pressed"),
        (TOGGLE, lib.IUIAutomationTogglePattern, "Toggle", "toggled"),
        (SELECTION_ITEM, lib.IUIAutomationSelectionItemPattern, "Select", "selected"),
        (EXPAND_COLLAPSE, lib.IUIAutomationExpandCollapsePattern, "Expand", "opened"),
    )
    for pattern_id, interface, method, done in attempts:
        try:
            pattern = element.GetCurrentPattern(pattern_id)
            if not pattern:
                continue
            getattr(pattern.QueryInterface(interface), method)()
            return done
        except Exception as exc:
            log.debug("Pattern %s failed on %s: %r", pattern_id, wanted.label, exc)
    rect = element.CachedBoundingRectangle
    if rect.right <= rect.left or rect.bottom <= rect.top:
        raise UIAError(f"The {wanted.label} cannot be pressed.")
    sendinput.click_at((rect.left + rect.right) // 2, (rect.top + rect.bottom) // 2)
    return "clicked"


def _top_window(element: Any) -> int:
    """The top-level window an element belongs to (works for WebView2 and other child processes,
    where the element's process is not the window's)."""
    uia = _get()
    walker = uia.client.ControlViewWalker
    root = uia.client.GetRootElement()
    current, handle = element, 0
    for _ in range(MAX_PARENT_STEPS):
        if not current or uia.client.CompareElements(current, root):
            break
        handle = current.CurrentNativeWindowHandle or handle
        parent = walker.GetParentElement(current)
        if not parent or uia.client.CompareElements(parent, root):
            return int(current.CurrentNativeWindowHandle or handle or 0)
        current = parent
    return int(handle or 0)


def focused_control(hwnd: int) -> Control | None:
    """The control with the keyboard focus, if it is inside this window."""
    uia = _get()
    try:
        element = uia.client.GetFocusedElement()
        element = element.BuildUpdatedCache(uia.cache)
    except Exception:
        return None
    if _top_window(element) != hwnd:
        return None
    if element.CachedControlType not in TYPABLE_KINDS and not _cached(
        element, "IsValuePatternAvailable"
    ):
        return Control(kind=KINDS.get(element.CachedControlType, "control"), name="")
    return _control(element, 0)


def focused_text(hwnd: int) -> str | None:
    """The text in the focused field of this window, or None if the focus is not in it."""
    uia = _get()
    try:
        element = uia.client.GetFocusedElement().BuildUpdatedCache(uia.cache)
    except Exception:
        return None
    if _top_window(element) != hwnd:
        return None
    value = _cached(element, "ValueValue")
    if isinstance(value, str) and value:
        return value
    if _cached(element, "IsTextPatternAvailable"):
        return _document_text(element) or ""
    return ""


def focus_field(hwnd: int, field: Control | None = None) -> Control:
    """Put the keyboard focus in a text field of this window and return it.

    With `field`, that one. Otherwise keep the focused field if there is one, else take the first
    visible field. The caller has already brought the window to the front.
    """
    if field is None:
        current = focused_control(hwnd)
        if current is not None and current.kind in {KINDS[k] for k in TYPABLE_KINDS}:
            return current
        for element, control, _text in _walk(hwnd):
            if control is not None and element.CachedControlType in EDITABLE_KINDS:
                field = control
                break
        if field is None:
            raise UIAError("I can't find a place to type in that window.")
    element = find_control(hwnd, field)
    if not element.CachedIsEnabled:
        raise UIAError(f"The {field.label} is greyed out.")
    try:
        element.SetFocus()
    except Exception as exc:
        raise UIAError(f"Windows did not let me put the cursor in the {field.label}.") from exc
    return _control(element, field.occurrence)
