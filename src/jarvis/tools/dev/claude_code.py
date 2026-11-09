"""Claude Code by voice: open a project's session, list its sessions, and pass it a prompt
(ADR-105).

- `[claude.projects.<name>]` names a folder. Claude Code keeps its sessions per folder in
  `~/.claude/projects/<folder with every other character a hyphen>/<session id>.jsonl`, and
  Jarvis reads only each session's title and last prompt from the end of that file.
- **Visible:** `claude_open`, or `claude_ask` with `visible`, starts `claude.exe` in a new console
  window in that folder, resuming the session (and sending the prompt). Then it is your window.
- **Background:** `claude_ask` runs `claude -p` on the same session with the prompt on stdin,
  shows what Claude is doing in the chat, and says a short summary when it is done. Claude's
  edits, commands, and fetches each ask you first through Jarvis (`claude-hook gate`).

Safety: the prompt leaves this computer for Anthropic, so it always asks first and shows the
exact words. It is refused when outside content (a page, a file's text) is in the conversation,
because a prompt to Claude can become edits and commands. npm's `claude.cmd` is never run with
arguments, since cmd.exe would read characters like `&` in a prompt as commands.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import re
import shutil
import subprocess
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from jarvis.config import REPO_ROOT, ClaudeSettings, Settings
from jarvis.platform.known_folders import expand_folder
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

PROJECT_MATCH = 80
SESSION_MATCH = 70
RECENT_S = 120  # a session written to this recently may be open in another window
TAIL_BYTES = 512 * 1024
SPOKEN_CHARS = 300
SHOWN_CHARS = 2000
MAX_PROMPT_CHARS = 4000
LATEST_WORDS = {"latest", "last", "recent", "current", "newest"}
FILLER_WORDS = {"the", "my", "a", "session", "one", "chat", "claude"}
NEW_WORDS = {"new", "a new", "new session", "a new session", "fresh"}
_SESSION_ID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
_SENTENCE = re.compile(r"(?<=[.!?])\s+")

Show = Callable[[str], Awaitable[None]]


@dataclass(frozen=True)
class Session:
    id: str
    title: str
    modified: float  # seconds since the epoch


# Finding Claude Code


def claude_cli(settings: ClaudeSettings) -> Path:
    """claude.exe, never a batch file: cmd.exe would run what a prompt's `&` or `|` start."""
    configured = settings.cli.strip()
    found: Path | None = Path(configured) if configured else None
    if found is None:
        hit = shutil.which("claude.exe") or shutil.which("claude.cmd")
        found = Path(hit) if hit else None
    if found is None:
        raise ToolError(
            "Claude Code is not installed. Install it (npm install -g @anthropic-ai/claude-code) "
            "or set [claude] cli to claude.exe."
        )
    if found.suffix.casefold() in (".cmd", ".bat"):
        inner = found.parent / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
        if (inner / "claude.exe").is_file():
            return inner / "claude.exe"
        raise ToolError(f"{found.name} is a batch file; set [claude] cli to claude.exe.")
    if not found.is_file():
        raise ToolError(f"{found} does not exist; check [claude] cli.")
    return found


# Projects and sessions


def choose_project(settings: ClaudeSettings, spoken: str) -> str:
    projects = settings.projects
    if not projects:
        raise ToolError(
            "No Claude projects are set up. Add one to config/local.toml, for example "
            '[claude.projects.jarvis] folder = "C:/Projects/JARVIS".'
        )
    words = re.sub(
        r"\b(my|the|project|folder|repo|code|for|in|on|claude)\b", " ", spoken.casefold()
    )
    query = " ".join(words.split())
    if not query and len(projects) == 1:
        return next(iter(projects))
    best = process.extractOne(
        query or spoken.casefold(), {n: n.casefold() for n in projects}, scorer=fuzz.WRatio
    )
    if best is None or best[1] < PROJECT_MATCH:
        if len(projects) == 1 and not query:
            return next(iter(projects))
        raise ToolError(f"No Claude project matches '{spoken}'. Projects: {', '.join(projects)}.")
    return str(best[2])


def project_folder(settings: ClaudeSettings, name: str) -> Path:
    folder = expand_folder(settings.projects[name].folder).resolve()  # as Claude sees its cwd
    if not folder.is_dir():
        raise ToolError(f"The {name} project's folder {folder} does not exist.")
    return folder


def sessions_dir(folder: Path, home: Path | None = None) -> Path | None:
    """Claude Code's folder for one project's sessions, matched without regard to case."""
    root = (home or Path.home()) / ".claude" / "projects"
    wanted = re.sub(r"[^A-Za-z0-9]", "-", str(folder)).casefold()
    try:
        for entry in root.iterdir():
            if entry.is_dir() and entry.name.casefold() == wanted:
                return entry
    except OSError:
        return None
    return None


def session_title(path: Path) -> str:
    """The session's name, or else its last prompt, read from the end of its file."""
    try:
        with path.open("rb") as handle:
            handle.seek(max(0, path.stat().st_size - TAIL_BYTES))
            tail = handle.read().decode("utf-8", "replace")
    except OSError:
        return ""
    title = prompt = ""
    for line in tail.splitlines():
        if '"custom-title"' not in line and '"last-prompt"' not in line:
            continue
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if entry.get("type") == "custom-title":
            title = str(entry.get("customTitle") or "") or title
        elif entry.get("type") == "last-prompt":
            prompt = str(entry.get("lastPrompt") or "") or prompt
    text = " ".join((title or prompt).split())
    return text if len(text) <= 80 else text[:77] + "..."


def list_sessions(folder: Path, limit: int = 10, home: Path | None = None) -> list[Session]:
    """The project's sessions, newest first."""
    found = sessions_dir(folder, home)
    if found is None:
        return []
    files = []
    for path in found.glob("*.jsonl"):
        if _SESSION_ID.match(path.stem):
            with contextlib.suppress(OSError):
                files.append((path.stat().st_mtime, path))
    files.sort(reverse=True)
    return [Session(p.stem, session_title(p) or "untitled", t) for t, p in files[:limit]]


def choose_session(sessions: list[Session], spoken: str) -> Session | None:
    """The session meant, or None for a new one. Empty or "latest" is the newest."""
    said = " ".join(spoken.casefold().split())
    if said in NEW_WORDS:
        return None
    core = {word for word in said.split() if word not in FILLER_WORDS}
    if core <= LATEST_WORDS:
        return sessions[0] if sessions else None
    if not sessions:
        raise ToolError("This project has no Claude sessions yet; ask for a new one.")
    for session in sessions:
        if session.id == said:
            return session
    best = process.extractOne(
        said, {i: s.title.casefold() for i, s in enumerate(sessions)}, scorer=fuzz.WRatio
    )
    if best is None or best[1] < SESSION_MATCH:
        titles = "; ".join(s.title for s in sessions[:5])
        raise ToolError(f"No session matches '{spoken}'. The latest are: {titles}.")
    return sessions[int(best[2])]


def described(session: Session | None) -> str:
    return f'the session "{session.title}"' if session else "a new session"


def recently_used(session: Session | None, now: float | None = None) -> bool:
    return session is not None and (now or time.time()) - session.modified < RECENT_S


# Running Claude Code


def visible_command(cli: Path, session: Session | None, prompt: str, name: str) -> list[str]:
    command = [str(cli)]
    command += ["--resume", session.id] if session else ["--name", f"Jarvis: {name}"]
    if prompt:
        # A prompt that starts with "-" would be read as an option.
        command.append(f" {prompt}" if prompt.startswith("-") else prompt)
    return command


def background_command(
    cli: Path, session: Session | None, settings_file: Path, mode: str, name: str
) -> list[str]:
    command = [str(cli), "-p", "--output-format", "stream-json", "--verbose"]
    command += ["--permission-mode", mode, "--settings", str(settings_file)]
    command += ["--resume", session.id] if session else ["--name", f"Jarvis: {name}"]
    return command  # the prompt goes on stdin, never on the command line


def open_console(command: list[str], folder: Path) -> None:
    """A new console window (Windows Terminal when it is the default terminal)."""
    subprocess.Popen(
        command,
        cwd=folder,
        creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0),
        close_fds=True,
    )


def progress_line(event: dict[str, Any]) -> str | None:
    """ "editing app.py", "running npm test": what Claude is doing that changes things."""
    from jarvis.bridge.hook import GATED_TOOLS, permission_text

    if event.get("type") != "assistant":
        return None
    for block in (event.get("message") or {}).get("content") or []:
        if block.get("type") == "tool_use" and block.get("name") in GATED_TOOLS:
            return permission_text(str(block["name"]), block.get("input") or {})
    return None


@dataclass
class Outcome:
    ok: bool
    text: str = ""
    session_id: str = ""
    denied: list[str] = field(default_factory=list)
    error: str = ""


def read_result(event: dict[str, Any]) -> Outcome:
    from jarvis.bridge.hook import permission_text

    denied = [
        permission_text(str(d.get("tool_name") or ""), d.get("tool_input") or {})
        for d in event.get("permission_denials") or []
    ]
    text = str(event.get("result") or "").strip()
    failed = bool(event.get("is_error")) or event.get("subtype") not in (None, "success")
    return Outcome(
        ok=not failed,
        text=text,
        session_id=str(event.get("session_id") or ""),
        denied=list(dict.fromkeys(denied)),
        error=text if failed else "",
    )


def summary(project: str, outcome: Outcome, *, quiet: bool) -> tuple[str, str]:
    """What to show in the chat and what to say aloud."""
    if not outcome.ok:
        problem = outcome.error or "it stopped without an answer"
        shown = f"Claude stopped in {project}: {problem[:SHOWN_CHARS]}"
        return shown, f"Claude stopped in {project} with an error."
    denied = ""
    if outcome.denied:
        denied = (
            f" It was not allowed to {', '.join(outcome.denied[:5])}; open the session to "
            "approve that."
        )
    text = outcome.text or "it gave no answer."
    shown = f"Claude finished in {project}: {text[:SHOWN_CHARS]}{denied}"
    if quiet:
        return shown, f"Claude finished in {project}."
    said = ""
    for sentence in _SENTENCE.split(text):
        if said and len(said) + len(sentence) > SPOKEN_CHARS:
            break
        said = f"{said} {sentence}".strip()
    said = said[:SPOKEN_CHARS]
    tail = " Some steps were not allowed; open the session to approve them." if denied else ""
    return shown, f"Claude finished in {project}. {said}{tail}"


class ClaudeRuns:
    """Background `claude -p` runs, one per project at a time."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._runs: dict[str, asyncio.Task[None]] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self._show: Show | None = None
        self._say: Show | None = None
        self._quiet: Callable[[], bool] = lambda: False

    def attach(self, show: Show, say: Show, quiet: Callable[[], bool]) -> None:
        """Set by the app's background work; without it a run is awaited instead."""
        self._show, self._say, self._quiet = show, say, quiet

    @property
    def background(self) -> bool:
        return self._show is not None

    def running(self, project: str) -> bool:
        task = self._runs.get(project)
        return task is not None and not task.done()

    def settings_file(self) -> Path:
        from jarvis.bridge.hook import gate_settings

        path = self._settings.data_dir / "claude" / "run-settings.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(gate_settings(REPO_ROOT), indent=2), "utf-8")
        return path

    async def run(
        self, project: str, folder: Path, session: Session | None, prompt: str
    ) -> Outcome:
        cfg = self._settings.claude
        command = background_command(
            claude_cli(cfg), session, self.settings_file(), cfg.permission_mode, project
        )
        proc = await asyncio.create_subprocess_exec(
            *command,
            cwd=folder,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            limit=4 * 1024 * 1024,
        )
        self._procs[project] = proc
        try:
            return await asyncio.wait_for(self._follow(project, proc, prompt), cfg.run_timeout_s)
        except TimeoutError:
            proc.kill()
            minutes = round(cfg.run_timeout_s / 60)
            return Outcome(ok=False, error=f"it ran longer than {minutes} minutes, so I stopped it")
        finally:
            self._procs.pop(project, None)
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()

    async def _follow(self, project: str, proc: asyncio.subprocess.Process, prompt: str) -> Outcome:
        assert proc.stdin is not None
        assert proc.stdout is not None
        assert proc.stderr is not None
        proc.stdin.write(prompt.encode("utf-8"))
        await proc.stdin.drain()
        proc.stdin.close()
        outcome: Outcome | None = None
        async for raw in proc.stdout:
            try:
                event = json.loads(raw)
            except ValueError:
                continue
            if event.get("type") == "result":
                outcome = read_result(event)
                continue
            line = progress_line(event)
            if line and self._show is not None:
                await self._show(f"Claude in {project}: {line}")
        error = (await proc.stderr.read()).decode("utf-8", "replace").strip()
        await proc.wait()
        if outcome is not None:
            return outcome
        detail = error.splitlines()[-1][:300] if error else f"exit code {proc.returncode}"
        return Outcome(ok=False, error=detail)

    def start(self, project: str, folder: Path, session: Session | None, prompt: str) -> None:
        async def go() -> None:
            try:
                outcome = await self.run(project, folder, session, prompt)
            except Exception as exc:  # report it rather than lose it in a task
                log.exception("Claude run in %s failed", project)
                outcome = Outcome(ok=False, error=str(exc) or type(exc).__name__)
            shown, said = summary(project, outcome, quiet=self._quiet())
            if self._show is not None:
                await self._show(shown)
            if self._say is not None:
                await self._say(said)

        self._runs[project] = asyncio.create_task(go(), name=f"claude-{project}")

    async def stop(self, project: str) -> bool:
        proc = self._procs.get(project)
        if proc is None or proc.returncode is not None:
            return False
        proc.kill()
        return True


def _runs(ctx: ToolContext) -> ClaudeRuns:
    if not ctx.settings.claude.enabled:
        raise ToolError("Claude Code control is off ([claude] enabled).")
    runs = ctx.services.claude
    if runs is None:
        raise ToolError("Claude Code control is not available here.")
    return runs


def _session_for(ctx: ToolContext, project: str, spoken: str) -> Session | None:
    folder = project_folder(ctx.settings.claude, project)
    return choose_session(list_sessions(folder), spoken)


# Tools


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def claude_sessions(ctx: ToolContext, project: str = "") -> ToolResult:
    """List the user's recent Claude Code sessions in one of their projects, for "which Claude
    sessions do I have in jarvis".

    Args:
        project: The project name from config as the user said it, for example "jarvis".
    """
    _runs(ctx)
    name = choose_project(ctx.settings.claude, project)
    folder = project_folder(ctx.settings.claude, name)
    sessions = await asyncio.to_thread(list_sessions, folder, 5)
    if not sessions:
        return ToolResult.success(
            data={"project": name, "sessions": []}, speech=f"{name} has no Claude sessions yet."
        )
    titles = "; ".join(s.title for s in sessions)
    return ToolResult.success(
        data={"project": name, "sessions": [s.title for s in sessions]},
        speech=f"The latest Claude sessions in {name}: {titles}.",
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def claude_open(ctx: ToolContext, project: str = "", session: str = "") -> ToolResult:
    """Open Claude Code in a new window on one of the user's projects, resuming a session, for
    "open Claude for jarvis" or "open my phone fix session in Claude". Not for the Claude
    desktop app: plain "open Claude" is open_app.

    Args:
        project: The project name from config as the user said it, for example "jarvis".
        session: Which session: words from its name, "latest" (the default), or "new".
    """
    name = project  # the preparer resolved it to a project in config
    folder = project_folder(ctx.settings.claude, name)
    chosen = await asyncio.to_thread(_session_for, ctx, name, session)
    command = visible_command(claude_cli(ctx.settings.claude), chosen, "", name)
    await asyncio.to_thread(open_console, command, folder)
    return ToolResult.success(
        data={"project": name, "session": chosen.title if chosen else None},
        speech=f"Opening Claude in {name}, {described(chosen)}.",
    )


@claude_open.preparer
async def _prepare_open(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    _runs(ctx)
    name = choose_project(ctx.settings.claude, str(args.get("project") or ""))
    chosen = await asyncio.to_thread(_session_for, ctx, name, str(args.get("session") or ""))
    claude_cli(ctx.settings.claude)
    return Prepared(
        args={"project": name, "session": chosen.id if chosen else "new"},
        summary=f"Open Claude Code in {name}, {described(chosen)}",
    )


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, egress=True, timeout_s=7200)
async def claude_ask(
    ctx: ToolContext, prompt: str, project: str = "", session: str = "", visible: bool = False
) -> ToolResult:
    """Pass the user's prompt to Claude Code in one of their projects, for "tell Claude in
    jarvis to add a test for the phone module" or "ask Claude to fix the failing test". Claude
    works on the code; Jarvis says when it is done. Use the user's own words as the prompt.

    Args:
        prompt: The user's request for Claude, in their own words.
        project: The project name from config as the user said it, for example "jarvis".
        session: Which session: words from its name, "latest" (the default), or "new".
        visible: True to open the session in a window with the prompt sent, for "in a window"
            or "so I can watch".
    """
    runs = _runs(ctx)
    name = project  # the preparer resolved it to a project in config
    folder = project_folder(ctx.settings.claude, name)
    chosen = await asyncio.to_thread(_session_for, ctx, name, session)
    if visible:
        command = visible_command(claude_cli(ctx.settings.claude), chosen, prompt, name)
        await asyncio.to_thread(open_console, command, folder)
        return ToolResult.success(
            data={"project": name, "visible": True},
            speech=f"Sent to Claude in {name}, in a new window.",
        )
    if runs.running(name):
        raise ToolError(f"Claude is still working in {name}. Say 'stop Claude' to end it first.")
    if runs.background:
        runs.start(name, folder, chosen, prompt)
        return ToolResult.success(
            data={"project": name, "background": True},
            speech=f"Sent to Claude in {name}. I'll tell you when it's done.",
        )
    outcome = await runs.run(name, folder, chosen, prompt)
    shown, said = summary(name, outcome, quiet=ctx.services.quiet_speech)
    if not outcome.ok:
        raise ToolError(shown)
    return ToolResult.success(data={"project": name, "answer": shown}, speech=said)


@claude_ask.preparer
async def _prepare_ask(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    _runs(ctx)
    prompt = str(args.get("prompt") or "").strip()
    if not prompt:
        raise ToolError("There is no prompt for Claude. Ask the user what Claude should do.")
    if len(prompt) > MAX_PROMPT_CHARS:
        raise ToolError(f"That prompt is longer than {MAX_PROMPT_CHARS} characters.")
    name = choose_project(ctx.settings.claude, str(args.get("project") or ""))
    chosen = await asyncio.to_thread(_session_for, ctx, name, str(args.get("session") or ""))
    claude_cli(ctx.settings.claude)
    visible = bool(args.get("visible"))
    pinned = {
        "prompt": prompt,
        "project": name,
        "session": chosen.id if chosen else "new",
        "visible": visible,
    }
    how = "in a new window" if visible else "in the background"
    shown = prompt if len(prompt) <= 300 else prompt[:297] + "..."
    summary_text = f'Send to Claude Code in {name}, {described(chosen)}, {how}: "{shown}"'
    if ctx.flags.untrusted:
        return Prepared(
            pinned,
            summary_text,
            Risk.BLOCKED,
            "outside content (a page or a file's text) is in this conversation, and a prompt "
            "to Claude can become edits and commands. Start a new chat and say it again",
        )
    reason = None
    if recently_used(chosen):
        reason = "that session changed in the last two minutes, so it may be open in another window"
    return Prepared(pinned, summary_text, Risk.CONFIRM, reason)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def claude_stop(ctx: ToolContext, project: str = "") -> ToolResult:
    """Stop Claude Code working in the background on one of the user's projects, for "stop
    Claude" or "cancel the Claude job".

    Args:
        project: The project name from config as the user said it, for example "jarvis".
    """
    runs = _runs(ctx)
    name = choose_project(ctx.settings.claude, project)
    if not await runs.stop(name):
        return ToolResult.success(
            data={"stopped": False}, speech=f"Claude isn't working in {name}."
        )
    return ToolResult.success(data={"stopped": True}, speech=f"Stopped Claude in {name}.")
