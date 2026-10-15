"""Command line entry point: chat, ask, voice, setup-voice, audit, version."""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from jarvis import __version__
from jarvis.app import build_app
from jarvis.config import ConfigError, Settings, load_settings
from jarvis.console import ConsoleChannel, ConsoleRenderer, read_line
from jarvis.core.agent import TurnStatus
from jarvis.logging_setup import setup_logging
from jarvis.storage.db import Database
from jarvis.storage.repositories import AuditLog
from jarvis.voice.tts.base import TTSEngine


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="jarvis", description="Local-first desktop assistant")
    parser.add_argument("-v", "--verbose", action="store_true", help="show debug logs")
    sub = parser.add_subparsers(dest="command", required=True)

    for name, help_text in (("chat", "talk to Jarvis by typing"), ("ask", "run one command")):
        cmd = sub.add_parser(name, help=help_text)
        if name == "ask":
            cmd.add_argument("text", help="the command, in quotes")
        cmd.add_argument("--model", help="use a different model for this session")
        cmd.add_argument("--speak", action="store_true", help="also speak every reply aloud")

    voice = sub.add_parser("voice", help="talk to Jarvis: push-to-talk, optional wake word")
    voice.add_argument("--wake", action="store_true", help='also listen for "hey jarvis"')
    voice.add_argument("--model", help="use a different model for this session")
    voice.add_argument("--list-devices", action="store_true", help="list microphones and exit")

    sub.add_parser("setup-voice", help="download the speech, voice, and wake word models")

    sub.add_parser("index", help="rebuild the app and file indexes now")

    audit = sub.add_parser("audit", help="show recent tool calls from the audit log")
    audit.add_argument("--last", type=int, default=20, help="how many entries (default 20)")

    sub.add_parser("version", help="print the version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    console = Console()
    if args.command == "version":
        console.print(f"jarvis {__version__}")
        return 0
    if _is_store_python():
        console.print(
            "[yellow]This is the Microsoft Store Python, which hides Jarvis's data folder. "
            "Use `uv run jarvis ...` from the project folder instead (see ADR-019).[/yellow]"
        )

    try:
        settings = load_settings()
    except ConfigError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 2
    log_file = setup_logging(settings.data_dir, verbose=args.verbose)

    if args.command == "audit":
        return show_audit(settings, args.last, console)
    if args.command == "index":
        return rebuild_indexes(settings, console)
    if args.command in ("voice", "setup-voice"):
        try:
            from jarvis.voice import runner
        except ImportError:
            console.print(
                "[red]Voice support is not installed. Run: "
                "uv sync --extra voice --extra piper[/red]"
            )
            return 2
        if args.command == "setup-voice":
            return runner.setup_voice(settings, console)
        if args.list_devices:
            return runner.list_devices(console)
        if args.model:
            settings.llm.active().model = args.model
        return runner.run_voice(settings, console, wake=args.wake, verbose=args.verbose)

    if args.model:
        settings.llm.active().model = args.model
    once = args.text if args.command == "ask" else None
    return run_chat(
        settings,
        console,
        once=once,
        speak_replies=args.speak,
        verbose=args.verbose,
        log_file=str(log_file),
    )


def run_chat(
    settings: Settings,
    console: Console,
    *,
    once: str | None,
    speak_replies: bool,
    verbose: bool,
    log_file: str,
) -> int:
    with asyncio.Runner() as runner:
        app = build_app(settings, ConsoleChannel(console))
        app.bus.subscribe(ConsoleRenderer(console, verbose=verbose))
        try:
            warning = runner.run(app.llm.check())
            if warning:
                console.print(f"[yellow]{escape(warning)}[/yellow]")

            if once is not None:
                result = runner.run(app.agent.run_turn(once, source="cli"))
                if speak_replies and result.status is TurnStatus.OK:
                    runner.run(_speak_quietly(app.services.tts, result.text, console))
                return 0 if result.status is TurnStatus.OK else 1

            console.print(
                f"[bold]Jarvis {__version__}[/bold] [dim]model {escape(app.llm.model)}, "
                f"log {escape(log_file)}[/dim]\n"
                "[dim]Type a command. Ctrl+C stops the current command, /quit exits.[/dim]"
            )
            runner.run(
                app.start_reminders(lambda text: _speak_quietly(app.services.tts, text, console))
            )
            while True:
                console.print("[bold cyan]you[/bold cyan] > ", end="")
                try:
                    # Reading inside the event loop keeps reminders running while you type.
                    text = runner.run(read_line()).strip()
                except (EOFError, KeyboardInterrupt):
                    console.print()
                    break
                if not text:
                    continue
                if text.casefold() in {"/quit", "/exit", "quit", "exit"}:
                    break
                try:
                    result = runner.run(app.agent.run_turn(text, source="cli"))
                    if speak_replies and result.status is TurnStatus.OK:
                        runner.run(_speak_quietly(app.services.tts, result.text, console))
                except KeyboardInterrupt:  # a second Ctrl+C while a command runs
                    console.print("\n[dim]Exiting.[/dim]")
                    break
        finally:
            runner.run(app.aclose())
    return 0


def rebuild_indexes(settings: Settings, console: Console) -> int:
    from jarvis.services import build_services

    db = Database(settings.data_dir / "jarvis.db")
    try:
        services = build_services(settings, db)
        with console.status("Indexing installed apps..."):
            apps = asyncio.run(services.apps.refresh())
        console.print(f"{apps} apps indexed.")
        files = services.files
        for root in files.guard.roots:
            console.print(f"[dim]allowed folder: {escape(str(root))}[/dim]")
        if files.backend == "everything":
            console.print("File search uses Everything, so there is no file index to build.")
        else:
            with console.status("Indexing files in the allowed folders..."):
                count = asyncio.run(files.rebuild())
            console.print(f"{count} files and folders indexed.")
    finally:
        db.close()
    return 0


def _is_store_python() -> bool:
    return "PythonSoftwareFoundation.Python" in sys.base_prefix or (
        "WindowsApps" in sys.base_prefix
    )


async def _speak_quietly(tts: TTSEngine, text: str, console: Console) -> None:
    try:
        await tts.speak(text)
    except asyncio.CancelledError:
        await tts.stop()
    except RuntimeError as exc:
        console.print(f"[yellow]{escape(str(exc))}[/yellow]")


def show_audit(settings: Settings, last: int, console: Console) -> int:
    db_path = settings.data_dir / "jarvis.db"
    if not db_path.exists():
        console.print("No audit log yet. Run `jarvis chat` first.")
        return 0
    db = Database(db_path)
    try:
        rows = AuditLog(db).recent(last)
    finally:
        db.close()

    table = Table(title=f"Last {len(rows)} tool calls", show_lines=False)
    for column in ("time", "tool", "risk", "decision", "ok", "ms", "args", "error"):
        table.add_column(column, overflow="fold")
    for row in rows:
        when = datetime.fromisoformat(row["ts"]).astimezone().strftime("%m-%d %H:%M:%S")
        table.add_row(
            when,
            row["tool"],
            row["risk"] or "",
            row["decision"],
            "yes" if row["ok"] else "no",
            str(row["duration_ms"] or ""),
            escape(row["args_json"] or ""),
            escape(row["error"] or ""),
        )
    console.print(table)
    return 0
