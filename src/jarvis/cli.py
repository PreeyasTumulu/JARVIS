"""Command line entry point: chat, ask, voice, serve, setup-voice, index, contacts, whatsapp,
notifications, audit, version."""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import sys
from datetime import datetime
from pathlib import Path

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

    serve = sub.add_parser("serve", help="open the web UI (with voice, if installed)")
    serve.add_argument("--port", type=int, help="port on 127.0.0.1 (default from config)")
    serve.add_argument("--no-browser", action="store_true", help="do not open the browser")
    serve.add_argument("--no-voice", action="store_true", help="web page only, no microphone")
    serve.add_argument("--wake", action="store_true", help='also listen for "hey jarvis"')
    serve.add_argument("--model", help="use a different model for this session")
    serve.add_argument("--tray", action="store_true", help="show a tray icon (used at login)")

    sub.add_parser("setup-voice", help="download the speech, voice, and wake word models")

    sub.add_parser("index", help="rebuild the app and file indexes now")

    contacts = sub.add_parser("contacts", help="the people Jarvis can message")
    actions = contacts.add_subparsers(dest="action")
    actions.add_parser("list", help="show every contact (the default)")
    add = actions.add_parser("add", help="add a contact")
    add.add_argument("name", help='the name, in quotes if it has spaces, e.g. "Ravi Kumar"')
    add.add_argument("phone", help="the number with its country code, e.g. +919876543210")
    add.add_argument(
        "--alias", action="append", default=[], help="another name you use, e.g. Mom (repeatable)"
    )
    alias = actions.add_parser("alias", help="give a contact another name")
    alias.add_argument("name")
    alias.add_argument("alias")
    unalias = actions.add_parser("unalias", help="remove one of a contact's other names")
    unalias.add_argument("name")
    unalias.add_argument("alias")
    remove = actions.add_parser("remove", help="delete a contact")
    remove.add_argument("name")
    load = actions.add_parser("import", help="import a .vcf file exported from your phone")
    load.add_argument("file")

    notes = sub.add_parser("notifications", help="what Jarvis has kept from allowed apps")
    notes.add_argument(
        "action",
        nargs="?",
        choices=["list", "test"],
        default="list",
        help="list (the default), or test: show a test notification to read back",
    )

    startup = sub.add_parser("startup", help="start Jarvis at login (tray, voice, Hey Jarvis)")
    startup.add_argument(
        "action", nargs="?", choices=["status", "enable", "disable"], default="status"
    )

    whatsapp = sub.add_parser("whatsapp", help="link WhatsApp Web to Jarvis's own browser")
    whatsapp.add_argument("action", choices=["login"], help="scan the QR code once")

    audit = sub.add_parser("audit", help="show recent tool calls from the audit log")
    audit.add_argument("--last", type=int, default=20, help="how many entries (default 20)")

    sub.add_parser("version", help="print the version")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    _utf8_output()
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
    if args.command == "contacts":
        return manage_contacts(settings, args, console)
    if args.command == "whatsapp":
        return whatsapp_login(settings, console)
    if args.command == "notifications":
        return show_notifications(settings, args.action, console)
    if args.command == "startup":
        return manage_startup(args.action, console)
    if args.command == "serve":
        from jarvis.server.serve import run_serve

        if args.model:
            settings.llm.active().model = args.model
        return run_serve(
            settings,
            console,
            port=args.port or settings.server.port,
            open_browser=settings.server.open_browser and not args.no_browser,
            voice=not args.no_voice,
            wake=args.wake,
            verbose=args.verbose,
            tray=args.tray,
        )
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
                app.start_background(lambda text: _speak_quietly(app.services.tts, text, console))
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


def manage_contacts(settings: Settings, args: argparse.Namespace, console: Console) -> int:
    from jarvis.tools.messaging.contacts import ContactBook, ContactError

    db = Database(settings.data_dir / "jarvis.db")
    book = ContactBook(db, settings.contacts)
    try:
        action = args.action or "list"
        if action == "add":
            contact = book.add(args.name, args.phone, args.alias)
            console.print(f"Added {escape(contact.name)} ({contact.phone}).")
        elif action == "alias":
            contact = book.add_alias(args.name, args.alias)
            console.print(f"{escape(contact.name)} is also {escape(', '.join(contact.aliases))}.")
        elif action == "unalias":
            book.remove_alias(args.name, args.alias)
            console.print(f"Removed the name {escape(args.alias)}.")
        elif action == "remove":
            console.print(f"Removed {escape(book.remove(args.name).name)}.")
        elif action == "import":
            result = book.import_vcard(
                Path(args.file).read_text(encoding="utf-8", errors="replace")
            )
            console.print(f"Imported {len(result.added)} contacts.")
            for line in result.skipped:
                console.print(f"[dim]skipped {escape(line)}[/dim]")
        else:
            table = Table(title=f"{len(book.all())} contacts")
            for column in ("name", "phone", "also called"):
                table.add_column(column)
            for contact in book.all():
                table.add_row(
                    escape(contact.name), contact.phone, escape(", ".join(contact.aliases))
                )
            console.print(table)
    except (ContactError, OSError) as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 1
    finally:
        db.close()
    return 0


def show_notifications(settings: Settings, action: str, console: Console) -> int:
    from jarvis.platform import notifications as center
    from jarvis.tools.notifications.store import TEST_TITLE, Notifications

    if action == "test":
        center.show_toast(f"{TEST_TITLE}: Ravi", "Hello from Jarvis. Say: read my notifications.")
        console.print("Showed a test notification. Now ask Jarvis: read my notifications.")
        return 0
    db = Database(settings.data_dir / "jarvis.db")
    try:
        service = Notifications(db, settings.notifications)
        try:
            asyncio.run(service.refresh())
        except center.NotificationAccessError as exc:
            console.print(f"[yellow]{escape(str(exc))}[/yellow]")
        items = service.store.recent(include_read=True)
        allowed = ", ".join(settings.notifications.apps) or "none"
        table = Table(title=f"{len(items)} notifications kept (apps: {escape(allowed)})")
        for column in ("when", "app", "from", "text", "read"):
            table.add_column(column, overflow="fold")
        for item in items[:50]:
            when = item.created.astimezone().strftime("%m-%d %H:%M")
            read = "yes" if item.read else ""
            table.add_row(when, escape(item.app), escape(item.title), escape(item.body), read)
        console.print(table)
    finally:
        db.close()
    return 0


def manage_startup(action: str, console: Console, folder: Path | None = None) -> int:
    from jarvis.platform import startup

    path = startup.shortcut_path(folder)
    if action == "enable":
        launch = startup.launcher()
        startup.write_shortcut(path, launch)
        console.print(
            f'Jarvis will start at login: tray icon, voice, and "Hey Jarvis".\n'
            f"[dim]{escape(str(path))}\n{escape(launch.target)} {escape(launch.arguments)}[/dim]"
        )
    elif action == "disable":
        if path.exists():
            path.unlink()
            console.print("Jarvis will no longer start at login.")
        else:
            console.print("Jarvis was not set to start at login.")
    else:
        current = startup.read_shortcut(path)
        if current is None:
            console.print(
                "Jarvis does not start at login. Turn it on: uv run jarvis startup enable"
            )
        else:
            console.print(
                f"Jarvis starts at login.\n[dim]{escape(current.target)} "
                f"{escape(current.arguments)}[/dim]"
            )
    return 0


def whatsapp_login(settings: Settings, console: Console) -> int:
    from jarvis.storage.repositories import Preferences
    from jarvis.tools.base import ToolError
    from jarvis.tools.browser.session import BrowserManager
    from jarvis.tools.messaging.whatsapp import WhatsAppWeb

    console.print(
        "Opening WhatsApp Web in Jarvis's own browser profile. On your phone, open WhatsApp > "
        "Settings > Linked devices > Link a device, and scan the code. Waiting up to 3 minutes."
    )
    db = Database(settings.data_dir / "jarvis.db")
    browser = BrowserManager(settings)
    web = WhatsAppWeb(browser, Preferences(db), settings.whatsapp)

    async def link() -> bool:
        try:
            return await web.login(wait_s=180)
        finally:
            await browser.aclose()

    try:
        linked = asyncio.run(link())
    except ToolError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 1
    finally:
        db.close()
    if not linked:
        console.print("[yellow]The chat list did not appear, so it is not linked yet.[/yellow]")
        return 1
    console.print(
        "Linked. send_whatsapp now uses WhatsApp Web first. To unlink, remove the device in "
        "WhatsApp on your phone (Linked devices)."
    )
    return 0


def _utf8_output() -> None:
    """Write UTF-8 when output goes to a pipe or file, and nowhere when there is no console.

    Started at login through pythonw there is no console at all (sys.stdout is None); the log
    file still records everything.

    A real console prints any character, but a redirected stream on Windows defaults to the
    ANSI code page (cp1252), where spinner and non-English characters crash the program.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115 (lives as long as Jarvis)
    if sys.stderr is None:
        sys.stderr = open(os.devnull, "w", encoding="utf-8")  # noqa: SIM115
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").replace("-", "").lower()
        if encoding != "utf8" and isinstance(stream, io.TextIOWrapper):
            stream.reconfigure(encoding="utf-8", errors="replace")


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
