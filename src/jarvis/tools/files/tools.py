"""File tools: find, open, and read files inside the allowed folders, and resolve "this file"."""

from __future__ import annotations

import asyncio
import os
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any, Literal

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.files.index import query_words
from jarvis.tools.files.readers import read_document
from jarvis.tools.files.selection import current_selection
from jarvis.tools.registry import tool
from jarvis.tools.secrets import hide_secrets

_PATH_FILLER = {"path", "to", "users", "user", "c", "home"}
CLEAR_LEAD = 8  # how far ahead the best search hit must be to use it without asking


async def locate(ctx: ToolContext, raw: str) -> str:
    """A real path for what the model passed.

    Small models sometimes invent paths ("/path/to/my/jarvis/readme.md"). If the path does not
    exist, search for the words in it and use the best hit when it clearly stands out;
    otherwise fail with the closest real paths so the model can pick one or ask.
    """
    text = raw.strip().strip('"')
    candidate = Path(text)
    if candidate.is_absolute():
        resolved = await asyncio.to_thread(candidate.resolve, strict=False)
        guard = ctx.services.files.guard
        if not guard.inside(resolved) or await asyncio.to_thread(resolved.exists):
            return text  # outside paths go straight to the guard, which blocks them
    words = [w for w in query_words(re.sub(r"[\\/]", " ", text)) if w not in _PATH_FILLER]
    hits = await ctx.services.files.search(" ".join(words), limit=3) if words else []
    if hits and (len(hits) == 1 or hits[0].score - hits[1].score >= CLEAR_LEAD):
        return hits[0].path
    if hits:
        options = "; ".join(hit.path for hit in hits)
        raise ToolError(
            f"'{raw}' does not exist. Closest matches: {options}. Call again with one of these "
            "exact paths, or ask the user which one."
        )
    raise ToolError(f"'{raw}' does not exist and nothing similar is in the allowed folders.")


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=60)
async def find_file(
    ctx: ToolContext, query: str, kind: Literal["any", "file", "folder"] = "any"
) -> ToolResult:
    """Search the user's folders for files or folders by name and return their full paths.
    Use this first whenever the user names a file or document (resume, readme, invoice), before
    open_file, read_file, or vscode_open.

    Args:
        query: Words from the name, for example "resume" or "invoice march pdf".
        kind: Look for "file", "folder", or "any".
    """
    hits = await ctx.services.files.search(query, kind=kind, limit=5)
    if not hits:
        return ToolResult.failure(f"Nothing in the allowed folders matches '{query}'.")
    best = Path(hits[0].path)
    speech = f"I found {len(hits)}. The best match is {best.name} in {best.parent.name}."
    return ToolResult.success(data=[asdict(hit) for hit in hits], speech=speech)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=20)
async def open_file(ctx: ToolContext, path: str) -> ToolResult:
    """Open a file or folder at a full path with its default app (like double-clicking it).
    Get the path from find_file or get_selected_file first.

    Args:
        path: The full path, from find_file or get_selected_file.
    """
    await asyncio.to_thread(os.startfile, path)  # type: ignore[attr-defined,unused-ignore]
    return ToolResult.success(data={"opened": path}, speech=f"Opening {Path(path).name}.")


@open_file.preparer
async def _prepare_open(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    check = ctx.services.files.guard.check(await locate(ctx, args["path"]), opening=True)
    return Prepared(
        args={"path": str(check.path)},
        summary=f"Open {check.path}",
        risk=check.risk,
        reason=check.reason,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=60)
async def read_file(ctx: ToolContext, path: str) -> ToolResult:
    """Read the text of a file (text, code, PDF, or Word .docx) to answer questions about it.

    Args:
        path: The full path, from find_file or get_selected_file.
    """
    cfg = ctx.settings.files
    document = await asyncio.to_thread(
        read_document,
        Path(path),
        max_chars=cfg.read_max_chars,
        max_bytes=int(cfg.read_max_mb * 1_000_000),
    )
    data: dict[str, Any] = {"path": path, "text": document.text, "truncated": document.truncated}
    if document.pages is not None:
        data["pages"] = document.pages
    return ToolResult.success(data=hide_secrets(data, "text"))


@read_file.preparer
async def _prepare_read(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    check = ctx.services.files.guard.check(await locate(ctx, args["path"]))
    return Prepared(
        args={"path": str(check.path)},
        summary=f"Read {check.path}",
        risk=check.risk,
        reason=check.reason,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=30)
async def get_selected_file(ctx: ToolContext) -> ToolResult:
    """Find out which file the user means by "this file", "this document", "the selected file",
    or "what is this": the file selected in File Explorer or open in VS Code.
    """
    selection = await current_selection(ctx.services.files)
    if selection is None:
        return ToolResult.failure(
            "No File Explorer or VS Code window is open. Ask the user which file they mean."
        )
    guard = ctx.services.files.guard
    allowed = await asyncio.to_thread(
        lambda: [guard.allows(Path(p).resolve(strict=False)) for p in selection.paths]
    )
    paths = [{"path": p, "allowed": ok} for p, ok in zip(selection.paths, allowed, strict=True)]
    if not paths:
        reason = " ".join(selection.notes) or "Nothing is selected in File Explorer."
        return ToolResult.failure(f"{reason} Ask the user which file they mean.")
    data = {
        "source": selection.source,
        "files": paths,
        "folder": selection.folder,
        "notes": selection.notes,
    }
    return ToolResult.success(data=data)
