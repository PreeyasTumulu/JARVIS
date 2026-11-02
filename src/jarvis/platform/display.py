"""Screen brightness, locking, and screenshots.

Brightness goes through WMI (`WmiMonitorBrightness`), which only reaches built-in laptop panels;
external monitors need DDC/CI, which Windows does not expose to WMI (see docs/RISKS.md).
"""

from __future__ import annotations

import ctypes
import subprocess
from pathlib import Path

_NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
_GET = (
    "(Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightness -ErrorAction Stop "
    "| Select-Object -First 1).CurrentBrightness"
)
_SET = (
    "Get-CimInstance -Namespace root/WMI -ClassName WmiMonitorBrightnessMethods -ErrorAction Stop "
    "| Invoke-CimMethod -MethodName WmiSetBrightness "
    "-Arguments @{{Brightness=[byte]{level}; Timeout=[uint32]0}} | Out-Null; " + _GET
)


def _powershell(script: str) -> str:
    done = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=15,
        creationflags=_NO_WINDOW,
    )
    if done.returncode != 0:
        first = (done.stderr.strip().splitlines() or ["unknown error"])[0]
        raise OSError(first)
    return done.stdout.strip()


def get_brightness() -> int:
    """Brightness 0 to 100 of the built-in screen. Raises OSError without one."""
    return int(_powershell(_GET))


def set_brightness(level: int) -> int:
    """Set the built-in screen's brightness and return the new level."""
    return int(_powershell(_SET.format(level=max(0, min(100, level)))))


def lock_workstation() -> None:
    if not ctypes.windll.user32.LockWorkStation():
        raise OSError("Windows refused to lock the screen")


def capture_screen(path: Path) -> tuple[int, int]:
    """Save every monitor as one PNG. Returns (width, height)."""
    import mss
    import mss.tools

    path.parent.mkdir(parents=True, exist_ok=True)
    with mss.mss() as sct:
        shot = sct.grab(sct.monitors[0])  # monitor 0 is the whole virtual desktop
        mss.tools.to_png(shot.rgb, shot.size, output=str(path))
    return shot.size.width, shot.size.height
