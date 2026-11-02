"""Read and write clipboard text with the Win32 clipboard API (no extra dependency)."""

from __future__ import annotations

import ctypes
import time
from ctypes import wintypes

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

_user32.OpenClipboard.argtypes = [wintypes.HWND]
_user32.OpenClipboard.restype = wintypes.BOOL
_user32.CloseClipboard.restype = wintypes.BOOL
_user32.EmptyClipboard.restype = wintypes.BOOL
_user32.GetClipboardData.argtypes = [wintypes.UINT]
_user32.GetClipboardData.restype = wintypes.HANDLE
_user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
_user32.SetClipboardData.restype = wintypes.HANDLE
_user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
_user32.RegisterClipboardFormatW.restype = wintypes.UINT
_user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
_user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
_user32.CountClipboardFormats.restype = ctypes.c_int
_user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
_kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
_kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
_kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalLock.restype = ctypes.c_void_p
_kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalUnlock.restype = wintypes.BOOL
_kernel32.GlobalFree.argtypes = [wintypes.HGLOBAL]
_kernel32.GlobalFree.restype = wintypes.HGLOBAL


def _open() -> None:
    """Open the clipboard, retrying briefly: another app may be holding it."""
    for _ in range(10):
        if _user32.OpenClipboard(None):
            return
        time.sleep(0.05)
    raise OSError("The clipboard is busy in another app")


def get_text() -> str | None:
    """The clipboard's text, or None when it holds no text (an image, files, or nothing)."""
    _open()
    try:
        return _read_text()
    finally:
        _user32.CloseClipboard()


def _read_text() -> str | None:
    handle = _user32.GetClipboardData(CF_UNICODETEXT)
    if not handle:
        return None
    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        return None
    try:
        return ctypes.wstring_at(pointer)
    finally:
        _kernel32.GlobalUnlock(handle)


def sequence_number() -> int:
    """Changes whenever the clipboard does; asking does not touch the clipboard."""
    return int(_user32.GetClipboardSequenceNumber())


def get_text_for_history() -> str | None:
    """The clipboard's text, or None when there is none or the app that copied it asked for it
    not to be recorded, as password managers do."""
    _open()
    try:
        return None if _left_out_of_history() else _read_text()
    finally:
        _user32.CloseClipboard()


def _left_out_of_history() -> bool:
    if _user32.IsClipboardFormatAvailable(_user32.RegisterClipboardFormatW(_PRIVATE_FORMATS[0])):
        return True
    handle = _user32.GetClipboardData(_user32.RegisterClipboardFormatW(_PRIVATE_FORMATS[1]))
    if not handle:
        return False
    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        return True  # it asked something of us that we cannot read: leave it out
    try:
        return ctypes.c_uint32.from_address(pointer).value == 0
    finally:
        _kernel32.GlobalUnlock(handle)


# Formats that keep a value out of Win+V history and the cloud clipboard, and tell clipboard
# managers to skip it (Microsoft's "Cloud Clipboard and Clipboard History Formats").
_PRIVATE_FORMATS = (
    "ExcludeClipboardContentFromMonitorProcessing",
    "CanIncludeInClipboardHistory",
    "CanUploadToCloudClipboard",
)
_ZERO_DWORD = bytes(4)


def _put(fmt: int, data: bytes) -> None:
    handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, len(data))
    if not handle:
        raise OSError("Could not allocate clipboard memory")
    pointer = _kernel32.GlobalLock(handle)
    if not pointer:
        _kernel32.GlobalFree(handle)
        raise OSError("Could not lock clipboard memory")
    ctypes.memmove(pointer, data, len(data))
    _kernel32.GlobalUnlock(handle)
    if not _user32.SetClipboardData(fmt, handle):
        _kernel32.GlobalFree(handle)  # on success Windows owns the memory
        raise OSError("Windows refused the clipboard data")


def set_text(text: str, *, private: bool = False) -> None:
    """Put text on the clipboard. `private` keeps it out of clipboard history (dictation)."""
    _open()
    try:
        _user32.EmptyClipboard()
        _put(CF_UNICODETEXT, text.encode("utf-16-le") + bytes(2))
        if private:
            for name in _PRIVATE_FORMATS:
                _put(_user32.RegisterClipboardFormatW(name), _ZERO_DWORD)
    finally:
        _user32.CloseClipboard()


def clear() -> None:
    _open()
    try:
        _user32.EmptyClipboard()
    finally:
        _user32.CloseClipboard()


def holds_other_data() -> bool:
    """True when the clipboard holds something that is not text (an image, files), which
    Jarvis could not put back after borrowing the clipboard."""
    return bool(
        _user32.CountClipboardFormats() > 0
        and not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT)
    )
