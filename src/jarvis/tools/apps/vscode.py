"""VS Code adapter. Launches Code.exe directly (not the code.cmd batch file) with the file path."""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool


def find_code_exe() -> Path | None:
    """Code.exe sits two levels above bin/code.cmd; fall back to the usual install folders."""
    candidates: list[Path] = []
    cmd = shutil.which("code")
    if cmd:
        candidates.append(Path(cmd).resolve().parent.parent / "Code.exe")
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("PROGRAMFILES", "")):
        if base:
            folder = "Programs/Microsoft VS Code" if base.endswith("Local") else "Microsoft VS Code"
            candidates.append(Path(base) / folder / "Code.exe")
    return next((path for path in candidates if path.is_file()), None)


def spawn(args: list[str]) -> None:
    subprocess.Popen(args, creationflags=subprocess.DETACHED_PROCESS)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=20)
async def vscode_open(ctx: ToolContext, path: str, line: int | None = None) -> ToolResult:
    """Open a file or folder in Visual Studio Code, optionally at a line number.

    Args:
        path: Full path of a file or project folder (use find_file if you only know the name).
        line: Line number to jump to in a file.
    """
    exe = find_code_exe()
    if exe is None:
        raise ToolError("VS Code is not installed, or Code.exe could not be found.")
    args = [str(exe), "--goto", f"{path}:{line}"] if line else [str(exe), path]
    await asyncio.to_thread(spawn, args)
    where = f" at line {line}" if line else ""
    return ToolResult.success(
        data={"opened": path, "line": line}, speech=f"Opening {Path(path).name} in VS Code{where}."
    )


@vscode_open.preparer
async def _prepare_vscode(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    from jarvis.tools.files.tools import locate

    check = ctx.services.files.guard.check(await locate(ctx, args["path"]))
    line = args.get("line")
    return Prepared(
        args={"path": str(check.path), "line": line},
        summary=f"Open {check.path} in VS Code",
        risk=check.risk,
        reason=check.reason,
    )
