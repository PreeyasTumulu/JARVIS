"""Which installed browser Jarvis drives: your Windows default when it is Chromium based.

Playwright drives Chromium browsers. Edge and Chrome have Playwright channels; Brave does not,
so it is launched by its executable path. Jarvis always uses its own profile folders, never
your everyday browser profile (that one is locked while the browser runs).
"""

from __future__ import annotations

import logging
import os
import winreg
from dataclasses import dataclass
from pathlib import Path

log = logging.getLogger(__name__)

# The ProgId Windows stores for the default https handler, per browser.
PROG_IDS = {
    "brave": ("BraveHTML", "BraveBHTML", "BraveSSHTM"),
    "chrome": ("ChromeHTML", "ChromeBHTML", "ChromeSSHTM"),
    "msedge": ("MSEdgeHTM", "MSEdgeBHTML", "MSEdgeDHTML"),
}
BRAVE_RELATIVE = Path("BraveSoftware") / "Brave-Browser" / "Application" / "brave.exe"
USER_CHOICE = r"Software\Microsoft\Windows\Shell\Associations\UrlAssociations\https\UserChoice"
APP_PATHS = r"Software\Microsoft\Windows\CurrentVersion\App Paths\brave.exe"


@dataclass(frozen=True)
class BrowserChoice:
    name: str  # brave, chrome, msedge, chromium
    channel: str | None  # the Playwright channel, or None when launched by path
    executable: Path | None = None


def default_browser() -> str | None:
    """brave, chrome, or msedge when that is the Windows default for https; otherwise None."""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, USER_CHOICE) as key:
            prog_id = str(winreg.QueryValueEx(key, "ProgId")[0])
    except OSError:
        return None
    for name, ids in PROG_IDS.items():
        if prog_id.startswith(ids):
            return name
    return None


def find_brave() -> Path | None:
    """brave.exe from a per-user or machine-wide install, or the App Paths registration."""
    roots = [os.environ.get(var) for var in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)")]
    for root in roots:
        if root and (candidate := Path(root) / BRAVE_RELATIVE).is_file():
            return candidate
    for hive in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        try:
            with winreg.OpenKey(hive, APP_PATHS) as key:
                registered = Path(str(winreg.QueryValueEx(key, "")[0]).strip('"'))
        except OSError:
            continue
        if registered.is_file():
            return registered
    return None


def resolve_browser(channel: str, executable: str = "") -> BrowserChoice:
    """Turn [browser] channel (and an optional explicit path) into what Playwright launches.

    "auto" follows the Windows default browser when it is Brave, Chrome, or Edge, and falls
    back to Edge, which every Windows 11 has.
    """
    if executable:
        return BrowserChoice("custom", None, Path(executable))
    name = channel
    if channel == "auto":
        name = default_browser() or "msedge"
        if name == "brave" and find_brave() is None:
            name = "msedge"
    if name == "brave":
        path = find_brave()
        if path is None:
            raise FileNotFoundError(
                "Brave is not installed where Jarvis looks. Set [browser] executable to the "
                "full path of brave.exe in config/local.toml."
            )
        return BrowserChoice("brave", None, path)
    return BrowserChoice(name, name)
