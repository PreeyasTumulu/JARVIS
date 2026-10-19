"""Real locations of Documents, Desktop, Downloads, and friends (OneDrive often redirects them).

Config can say "{documents}" instead of a hard-coded path; this resolves it through Windows'
SHGetKnownFolderPath, which follows OneDrive and Group Policy redirection.
"""

from __future__ import annotations

import ctypes
import os
import uuid
from ctypes import wintypes
from pathlib import Path

_KNOWN = {
    "documents": "FDD39AD0-238F-46AF-ADB4-6C85480369C7",
    "desktop": "B4BFCC3A-DB2C-424C-B029-7FE99A87C641",
    "downloads": "374DE290-123F-4565-9164-39C4925E467B",
    "pictures": "33E28130-4E1E-4676-835A-98395C3BC3BB",
    "music": "4BD8D571-6D19-48D3-BE97-422220080E43",
    "videos": "18989B1D-99B5-455B-841C-AB7C74E4DDFC",
    "startup": "B97D20BB-F46A-4C97-BA10-5E3608430854",
}


class _GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", wintypes.DWORD),
        ("Data2", wintypes.WORD),
        ("Data3", wintypes.WORD),
        ("Data4", ctypes.c_ubyte * 8),
    ]


def known_folder(name: str) -> Path:
    """Path of a known folder such as "documents". Raises KeyError or OSError."""
    value = uuid.UUID(_KNOWN[name.casefold()])
    guid = _GUID(value.fields[0], value.fields[1], value.fields[2])
    guid.Data4[:] = list(value.bytes[8:])
    out = ctypes.c_wchar_p()
    result = ctypes.windll.shell32.SHGetKnownFolderPath(
        ctypes.byref(guid), 0, None, ctypes.byref(out)
    )
    try:
        if result != 0 or out.value is None:
            raise OSError(f"SHGetKnownFolderPath failed for {name} ({result:#x})")
        return Path(out.value)
    finally:
        ctypes.windll.ole32.CoTaskMemFree(out)


def expand_folder(spec: str) -> Path:
    """Expand "{documents}", "~", and environment variables in a configured folder."""
    text = spec.strip()
    if text.startswith("{") and "}" in text:
        name, rest = text[1:].split("}", 1)
        return known_folder(name) / rest.lstrip("/\\")
    return Path(os.path.expandvars(text)).expanduser()
