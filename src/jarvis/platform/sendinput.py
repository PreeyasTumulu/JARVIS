"""Synthetic keyboard and mouse input through Win32 SendInput.

Text is sent as Unicode characters (KEYEVENTF_UNICODE), so it arrives as written in any keyboard
layout, including non-English text and emoji, and an input method (IME) does not change it.
Shortcuts are sent as virtual keys with their modifiers held down.

Input goes to whichever window has the focus, so callers check the foreground window first
(tools/ui/tools.py). Windows silently drops input aimed at a window that runs as administrator
(UIPI), which is why `is_elevated` exists.
"""

from __future__ import annotations

import ctypes
import time
from collections.abc import Sequence
from ctypes import wintypes

user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
advapi32 = ctypes.WinDLL("advapi32", use_last_error=True)

INPUT_MOUSE = 0
INPUT_KEYBOARD = 1
KEYEVENTF_EXTENDEDKEY = 0x0001
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
MOUSEEVENTF_LEFTDOWN = 0x0002
MOUSEEVENTF_LEFTUP = 0x0004
VK_RETURN = 0x0D
VK_TAB = 0x09
CHAR_PAUSE_S = 0.012  # between typed characters (see type_unicode)
WIDE_CHAR_PAUSE_S = 0.08  # after an emoji or another character outside the BMP
# Keys that sit on the extended part of the keyboard; without the flag, some apps read the
# number pad versions instead (End becomes 1, arrows become 2, 4, 6, 8).
EXTENDED_KEYS = {0x21, 0x22, 0x23, 0x24, 0x25, 0x26, 0x27, 0x28, 0x2D, 0x2E, 0x5D}

PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
TOKEN_QUERY = 0x0008
TOKEN_ELEVATION = 20
ERROR_ACCESS_DENIED = 5


class MOUSEINPUT(ctypes.Structure):
    _fields_ = (
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class KEYBDINPUT(ctypes.Structure):
    _fields_ = (
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    )


class _INPUTUNION(ctypes.Union):
    _fields_ = (("mi", MOUSEINPUT), ("ki", KEYBDINPUT))


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = (("type", wintypes.DWORD), ("u", _INPUTUNION))


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
user32.SendInput.restype = wintypes.UINT
user32.SetCursorPos.argtypes = [ctypes.c_int, ctypes.c_int]
kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
advapi32.OpenProcessToken.argtypes = [
    wintypes.HANDLE,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.HANDLE),
]
advapi32.GetTokenInformation.argtypes = [
    wintypes.HANDLE,
    ctypes.c_int,
    ctypes.c_void_p,
    wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
]


def _key(vk: int = 0, scan: int = 0, flags: int = 0) -> INPUT:
    item = INPUT(type=INPUT_KEYBOARD)
    item.ki = KEYBDINPUT(vk, scan, flags, 0, 0)
    return item


def _send(items: Sequence[INPUT]) -> None:
    array = (INPUT * len(items))(*items)
    sent = user32.SendInput(len(items), array, ctypes.sizeof(INPUT))
    if sent != len(items):
        raise OSError(ctypes.get_last_error(), "Windows refused the synthetic input")


def type_unicode(text: str) -> None:
    """Type text into the focused window, one paced character at a time. Newlines press Enter
    and tabs press Tab.

    Apps built on the Text Services Framework (Windows 11 Notepad) read input late. A burst of
    Unicode characters then arrives as the last one repeated ("hello world" became "hello
    ddddd"), and real key presses lose their Shift ("Typing" became "tping"). Measured on
    Notepad, 8 ms between characters was enough; emoji take longer to render.
    """
    for char in text.replace("\r\n", "\n").replace("\r", "\n"):
        if char in "\n\t":
            vk = VK_RETURN if char == "\n" else VK_TAB
            _send([_key(vk), _key(vk, flags=KEYEVENTF_KEYUP)])
            time.sleep(CHAR_PAUSE_S)
            continue
        encoded = char.encode("utf-16-le")
        items = []
        for index in range(0, len(encoded), 2):  # characters outside the BMP are two units
            unit = int.from_bytes(encoded[index : index + 2], "little")
            items += [
                _key(scan=unit, flags=KEYEVENTF_UNICODE),
                _key(scan=unit, flags=KEYEVENTF_UNICODE | KEYEVENTF_KEYUP),
            ]
        _send(items)
        time.sleep(CHAR_PAUSE_S if len(encoded) == 2 else WIDE_CHAR_PAUSE_S)


def press_combo(modifiers: Sequence[int], key: int) -> None:
    """Hold the modifier keys, tap the key, release the modifiers in reverse order."""

    def flags(vk: int, up: bool) -> int:
        return (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_KEYS else 0) | (
            KEYEVENTF_KEYUP if up else 0
        )

    items = [_key(vk, flags=flags(vk, False)) for vk in modifiers]
    items += [_key(key, flags=flags(key, False)), _key(key, flags=flags(key, True))]
    items += [_key(vk, flags=flags(vk, True)) for vk in reversed(modifiers)]
    _send(items)


def wait_for_keys_released(vks: Sequence[int], timeout_s: float) -> bool:
    """Wait until none of the keys is physically held, so synthetic text is not read as a
    shortcut (a held Ctrl turns typed letters into commands). False if they stayed down."""
    deadline = time.monotonic() + timeout_s
    while any(user32.GetAsyncKeyState(vk) & 0x8000 for vk in vks):
        if time.monotonic() >= deadline:
            return False
        time.sleep(0.02)
    return True


def click_at(x: int, y: int) -> None:
    """Left click at screen coordinates (physical pixels; the process is DPI aware)."""
    user32.SetCursorPos(x, y)
    down, up = INPUT(type=INPUT_MOUSE), INPUT(type=INPUT_MOUSE)
    down.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTDOWN, 0, 0)
    up.mi = MOUSEINPUT(0, 0, 0, MOUSEEVENTF_LEFTUP, 0, 0)
    _send([down, up])


def is_elevated(pid: int) -> bool:
    """Whether a process runs as administrator. Its token cannot even be opened from a normal
    process, which is itself the answer."""
    process = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not process:
        return ctypes.get_last_error() == ERROR_ACCESS_DENIED
    token = wintypes.HANDLE()
    try:
        if not advapi32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)):
            return ctypes.get_last_error() == ERROR_ACCESS_DENIED
        try:
            elevation = wintypes.DWORD()
            size = wintypes.DWORD()
            ok = advapi32.GetTokenInformation(
                token, TOKEN_ELEVATION, ctypes.byref(elevation), 4, ctypes.byref(size)
            )
            return bool(ok and elevation.value)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(process)
