"""Start Jarvis at login: a shortcut in your Startup folder (no registry edits, ADR-047).

The shortcut runs uv's windowless launcher, `uvw run --project <repo> ... pythonw -m jarvis serve
--tray --wake --no-browser`, so the environment is synced after a `git pull` and no console
window opens. Without uvw it falls back to the project's own pythonw.
"""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from jarvis.config import REPO_ROOT
from jarvis.platform.known_folders import known_folder

SHORTCUT = "Jarvis.lnk"
SERVE_ARGS = "-m jarvis serve --tray --wake --no-browser"
MINIMIZED = 7  # SW_SHOWMINNOACTIVE: nothing pops up at login


@dataclass(frozen=True)
class Launcher:
    target: str
    arguments: str
    folder: str


def shortcut_path(folder: Path | None = None) -> Path:
    return (folder or known_folder("startup")) / SHORTCUT


def launcher(project: Path = REPO_ROOT) -> Launcher:
    uvw = shutil.which("uvw")
    if uvw:
        arguments = f'run --project "{project}" --extra voice --extra piper pythonw {SERVE_ARGS}'
        return Launcher(uvw, arguments, str(project))
    pythonw = project / ".venv" / "Scripts" / "pythonw.exe"
    return Launcher(str(pythonw), SERVE_ARGS, str(project))


def write_shortcut(path: Path, launch: Launcher) -> None:
    import comtypes.client

    shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
    link = shell.CreateShortcut(str(path))
    link.TargetPath = launch.target
    link.Arguments = launch.arguments
    link.WorkingDirectory = launch.folder
    link.WindowStyle = MINIMIZED
    link.Description = "Jarvis, your local assistant"
    link.Save()


def read_shortcut(path: Path) -> Launcher | None:
    if not path.exists():
        return None
    import comtypes.client

    shell = comtypes.client.CreateObject("WScript.Shell", dynamic=True)
    link = shell.CreateShortcut(str(path))
    return Launcher(str(link.TargetPath), str(link.Arguments), str(link.WorkingDirectory))
