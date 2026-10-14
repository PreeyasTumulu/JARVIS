"""Work out what "this file" means: the selection in File Explorer or the file open in VS Code.

Explorer exposes its windows and selections through the Shell.Application COM object (read
via PowerShell, so no extra dependency). VS Code only shows the file name and workspace in its
window title, so the full path is looked up in the file index; that part is a best guess.
"""

from __future__ import annotations

import asyncio
import json
import re
import subprocess
from dataclasses import dataclass, field
from typing import Literal

from jarvis.platform import windows as win
from jarvis.tools.files.index import FileIndex

_TERMINALS = {"windowsterminal", "cmd", "powershell", "pwsh", "conhost", "openconsole", "python"}
_VSCODE_PAGES = {"welcome", "settings", "extensions", "keyboard shortcuts", "release notes"}
_SHELL_SCRIPT = r"""
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$shell = New-Object -ComObject Shell.Application
$items = foreach ($w in $shell.Windows()) {
  try {
    $doc = $w.Document
    [pscustomobject]@{ hwnd = [int64]$w.HWND; folder = $doc.Folder.Self.Path;
                       selected = @($doc.SelectedItems() | ForEach-Object { $_.Path }) }
  } catch {}
}
ConvertTo-Json -InputObject @($items) -Depth 3 -Compress
"""


@dataclass(frozen=True)
class Selection:
    source: Literal["explorer", "vscode"]
    paths: list[str]
    folder: str | None = None
    window_title: str = ""
    notes: list[str] = field(default_factory=list)


def explorer_windows() -> dict[int, tuple[str | None, list[str]]]:
    """Blocking. hwnd to (current folder, selected paths) for every File Explorer window."""
    completed = subprocess.run(
        ["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", _SHELL_SCRIPT],
        capture_output=True,
        timeout=20,
        creationflags=subprocess.CREATE_NO_WINDOW,
    )
    text = completed.stdout.decode("utf-8", errors="replace").strip() or "[]"
    data = json.loads(text)
    items = data if isinstance(data, list) else [data]
    return {
        int(item["hwnd"]): (item.get("folder"), [p for p in item.get("selected") or [] if p])
        for item in items
        if item and item.get("hwnd")
    }


async def current_selection(index: FileIndex) -> Selection | None:
    """The most recently used Explorer or VS Code window decides (terminals are skipped)."""
    windows, explorer = await asyncio.gather(
        asyncio.to_thread(win.list_windows), asyncio.to_thread(explorer_windows)
    )
    for window in windows:
        exe = window.exe.casefold()
        if exe in _TERMINALS:
            continue
        if window.hwnd in explorer:
            folder, selected = explorer[window.hwnd]
            return Selection("explorer", selected, folder, window.title)
        if exe == "code":
            return await _vscode_selection(window.title, index)
    return None


async def _vscode_selection(title: str, index: FileIndex) -> Selection:
    clean = re.sub("^●\\s*", "", title).strip()
    parts = [part.strip() for part in clean.split(" - ")]
    if len(parts) < 3 or parts[0].casefold() in _VSCODE_PAGES:
        return Selection("vscode", [], None, title, ["No file is open in the VS Code editor."])
    file_name, workspace = parts[0], parts[1]
    matches = await index.find_by_name(file_name)
    in_workspace = [p for p in matches if workspace.casefold() in p.casefold()]
    paths = in_workspace or matches
    notes = []
    if not paths:
        notes.append(f"{file_name} is open in VS Code but is not inside the allowed folders.")
    elif len(paths) > 1:
        notes.append("Several files have this name; ask the user which one if it matters.")
    return Selection("vscode", paths[:5], None, title, notes)
