"""Command line entry point: `jarvis chat`, `jarvis ask`, `jarvis audit`, `jarvis version`."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from jarvis import __version__
from jarvis.app import build_app
from jarvis.config import ConfigError, Settings, load_settings
from jarvis.console import ConsoleChannel, ConsoleRenderer
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

    try:
        settings = load_settings()
    except ConfigError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 2
    log_file = setup_logging(settings.data_dir, verbose=args.verbose)

    if args.command == "audit":
        return show_audit(settings, args.last, console)

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
            while True:
                try:
                    text = console.input("[bold cyan]you[/bold cyan] > ").strip()
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
