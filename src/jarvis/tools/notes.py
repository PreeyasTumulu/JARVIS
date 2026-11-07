"""Notes: "note that the meeting moved to 5" goes into a Markdown file per day (ADR-088).

The folder is `[notes] folder` (default `{documents}\\Jarvis Notes`), outside Jarvis's data
folder, so the notes are yours to open, edit, sync, or delete like any document. Each day is
`2026-11-07.md` with a heading and one timestamped line per note. Reading notes back marks the
text as data: anything can edit a file in Documents, so it is never taken as instructions.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
from datetime import date, datetime, timedelta
from pathlib import Path

from jarvis.platform.known_folders import expand_folder
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

MAX_NOTE_CHARS = 2000
_WEEKDAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_LINE = re.compile(r"^- (\d{1,2}:\d{2}) (.*)$")


def notes_folder(ctx: ToolContext) -> Path:
    return expand_folder(ctx.settings.notes.folder)


def note_day(when: str, today: date) -> date:
    """ "today", "yesterday", a weekday (the last one), "3 days ago", or 2026-11-07."""
    text = " ".join(when.casefold().split()).removeprefix("on ").removeprefix("last ")
    if text in ("", "today", "now"):
        return today
    if text == "yesterday":
        return today - timedelta(days=1)
    if text in _WEEKDAYS:
        back = (today.weekday() - _WEEKDAYS.index(text)) % 7 or 7
        return today - timedelta(days=back)
    ago = re.fullmatch(r"(\d{1,3}) days? ago", text)
    if ago:
        return today - timedelta(days=int(ago[1]))
    try:
        return date.fromisoformat(text)
    except ValueError:
        raise ToolError(
            f"I couldn't tell which day '{when}' is. Say today, yesterday, a weekday, or a date."
        ) from None


def day_file(folder: Path, day: date) -> Path:
    return folder / f"{day.isoformat()}.md"


def spoken_day(day: date, today: date) -> str:
    if day == today:
        return "today"
    if day == today - timedelta(days=1):
        return "yesterday"
    return f"{day:%A} {day.day} {day:%B}"


def _append(path: Path, heading: str, line: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    new = not path.exists()
    with path.open("a", encoding="utf-8", newline="\n") as handle:
        if new:
            handle.write(f"# {heading}\n\n")
        handle.write(line + "\n")


def _now(ctx: ToolContext) -> datetime:
    return datetime.fromtimestamp(ctx.services.reminders.clock())


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=10)
async def take_note(ctx: ToolContext, text: str) -> ToolResult:
    """Write down a note for the user, for "note that the meeting moved to 5" or "jot down
    buy milk". It goes into today's notes file.

    Args:
        text: The note in the user's words, without "note that".
    """
    note = " ".join(text.split())
    note = re.sub(r"^(that|down)\s+", "", note, flags=re.I).strip()
    if not note:
        raise ToolError("Ask the user what to note down.")
    if len(note) > MAX_NOTE_CHARS:
        raise ToolError(f"That note is too long; notes are up to {MAX_NOTE_CHARS} characters.")
    now = _now(ctx)
    path = day_file(notes_folder(ctx), now.date())
    heading = f"Notes, {now.day} {now:%B %Y}"
    await asyncio.to_thread(_append, path, heading, f"- {now:%H:%M} {note}")
    return ToolResult.success(data={"file": str(path), "note": note}, speech="Noted.")


def _read(path: Path) -> list[tuple[str, str]]:
    if not path.exists():
        return []
    found = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        match = _LINE.match(raw.strip())
        if match:
            found.append((match[1], match[2]))
        elif raw.strip() and not raw.startswith("#") and found:
            found[-1] = (found[-1][0], f"{found[-1][1]} {raw.strip()}")  # a line you added
    return found


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=10)
async def read_notes(ctx: ToolContext, day: str = "today") -> ToolResult:
    """Read the user's notes from one day, for "read my notes" or "what did I note yesterday".

    Args:
        day: "today", "yesterday", a weekday such as "monday", or a date like 2026-11-07.
    """
    today = _now(ctx).date()
    chosen = note_day(day, today)
    path = day_file(notes_folder(ctx), chosen)
    notes = await asyncio.to_thread(_read, path)
    when = spoken_day(chosen, today)
    if not notes:
        return ToolResult.success(data=[], speech=f"You have no notes from {when}.")
    items = [{"time": t, "note": n} for t, n in notes]
    if len(notes) == 1:
        speech = f"One note from {when}: {notes[0][1]}"
    else:
        speech = f"{len(notes)} notes from {when}. The latest: {notes[-1][1]}"
    return ToolResult.success(data={"day": chosen.isoformat(), "notes": items}, speech=speech)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def open_notes(ctx: ToolContext, day: str = "today") -> ToolResult:
    """Open the user's notes from one day in Notepad, to see or edit them ("open my notes").

    Args:
        day: "today", "yesterday", a weekday, or a date like 2026-11-07.
    """
    today = _now(ctx).date()
    chosen = note_day(day, today)
    path = day_file(notes_folder(ctx), chosen)
    if not await asyncio.to_thread(path.exists):
        if chosen != today:
            raise ToolError(f"There are no notes from {spoken_day(chosen, today)}.")
        heading = f"Notes, {today.day} {today:%B %Y}"
        await asyncio.to_thread(_append, path, heading, "")
    await asyncio.to_thread(spawn_notepad, path)
    return ToolResult.success(
        data={"file": str(path)}, speech=f"Opening your notes from {spoken_day(chosen, today)}."
    )


def spawn_notepad(path: Path) -> None:
    subprocess.Popen(["notepad.exe", str(path)], close_fds=True)
