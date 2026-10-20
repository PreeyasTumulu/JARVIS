"""Command line entry point: chat, ask, voice, serve, setup-voice, index, contacts, whatsapp,
notifications, mail, calendar, mcp, audit, version."""

from __future__ import annotations

import argparse
import asyncio
import io
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.markup import escape
from rich.table import Table

from jarvis import __version__
from jarvis.app import build_app
from jarvis.bridge.service import bridge_running
from jarvis.config import REPO_ROOT, ConfigError, Settings, load_settings
from jarvis.console import ConsoleChannel, ConsoleRenderer, read_line
from jarvis.core.agent import TurnStatus
from jarvis.logging_setup import setup_logging
from jarvis.storage.db import Database
from jarvis.storage.repositories import AuditLog
from jarvis.tools.mcp.hub import McpHub, RemoteTool
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
    voice.add_argument(
        "--wake-test",
        type=float,
        nargs="?",
        const=30.0,
        metavar="SECONDS",
        help='show the microphone level and the "hey jarvis" score live (default 30 s)',
    )

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

    mail = sub.add_parser("mail", help="check that Jarvis can sign in to your mailbox")
    mail.add_argument("action", choices=["test"], help="sign in and count unread email")
    calendar = sub.add_parser("calendar", help="check that Jarvis can read your calendar")
    calendar.add_argument("action", choices=["test"], help="download it and count events")
    mcp = sub.add_parser("mcp", help="MCP servers: list them, see their tools, test one")
    mcp.add_argument(
        "action",
        nargs="?",
        choices=["list", "tools", "test"],
        default="list",
        help="list servers (the default), tools: everything a server offers, test: connect "
        "and show what Jarvis exposes",
    )
    mcp.add_argument("server", nargs="?", help="the server name, for tools and test")

    hook = sub.add_parser(
        "claude-hook", help="answer Claude Code's questions through Jarvis (its hooks run this)"
    )
    hook.add_argument(
        "action",
        nargs="?",
        default="run",
        choices=["run", "install", "uninstall", "status", "test"],
        help="run (what Claude Code calls), install or uninstall the hooks, status, or test",
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
    if args.command == "claude-hook":
        return claude_hook(settings, args.action, console)
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
    if args.command == "mail":
        return test_mail(settings, console)
    if args.command == "calendar":
        return test_calendar(settings, console)
    if args.command == "mcp":
        return manage_mcp(settings, args.action, args.server, console)
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
        if args.wake_test is not None:
            return runner.wake_test(settings, console, seconds=args.wake_test)
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


def test_mail(settings: Settings, console: Console) -> int:
    """Sign in and count unread email. Prints counts only, never a sender or subject."""
    from jarvis.tools.mail.mailbox import Mailbox, MailError

    mailbox = Mailbox(settings.mail)
    try:
        with console.status(f"Signing in to {settings.mail.imap_host}..."):
            unread = asyncio.run(mailbox.count(unread_only=True))
            total = asyncio.run(mailbox.count(unread_only=False))
    except MailError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 1
    console.print(
        f"[green]Signed in as {escape(settings.mail.address)}.[/green] "
        f"{settings.mail.folder}: {total} emails, {unread} unread. "
        'Now ask Jarvis: "any new email?"'
    )
    return 0


def manage_mcp(settings: Settings, action: str, server: str | None, console: Console) -> int:
    """List servers, show a server's tools, or connect and show what Jarvis exposes."""
    from jarvis.tools.mcp.hub import McpError, McpHub, missing_vars
    from jarvis.tools.mcp.tools import risk_for, tool_name

    hub = McpHub(settings.mcp, log_dir=settings.data_dir / "logs")
    servers = hub.configured()
    if action == "list":
        if not servers:
            console.print("No MCP servers are enabled (see [mcp.servers] in config/jarvis.toml).")
            return 0
        table = Table(title="MCP servers")
        for column in ("name", "how", "tools listed", "trusted", "status"):
            table.add_column(column)
        for name, cfg in servers.items():
            missing = missing_vars(cfg)
            how = cfg.url or cfg.command
            status = f"needs {', '.join(missing)} in .env" if missing else "ready to start"
            table.add_row(
                name, escape(how), str(len(cfg.tools)), "yes" if cfg.trusted else "no", status
            )
        console.print(table)
        return 0
    if not server or server not in servers:
        console.print(
            f"[red]Name an enabled server: {', '.join(servers) or 'none configured'}.[/red]"
        )
        return 2
    cfg = servers[server]
    missing = missing_vars(cfg)
    if missing:
        console.print(f"[red]{escape(server)} needs {', '.join(missing)} in .env first.[/red]")
        return 1
    try:
        with console.status(f"Starting {server}..."):
            if action == "tools":
                found = asyncio.run(hub.offered(server))
            else:
                found = asyncio.run(_mcp_exposed(hub, server))
    except McpError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 1
    if action == "test" and not found:
        console.print(f"[red]None of the tools listed for {escape(server)} exist on it.[/red]")
        return 1
    title = f"{server}: {len(found)} tools" + (
        " offered" if action == "tools" else " Jarvis exposes"
    )
    table = Table(title=title)
    for column in (
        "Jarvis name" if action == "test" else "tool",
        "read-only",
        "asks first",
        "description",
    ):
        table.add_column(column)
    for remote in found:
        listed = remote.name in cfg.tools or cfg.tools == ["*"]
        asks = risk_for(remote, cfg).value if listed else "not exposed"
        shown = tool_name(server, remote.name) if action == "test" else remote.name
        table.add_row(
            escape(shown),
            "yes" if remote.read_only else "no",
            asks,
            escape(remote.description.splitlines()[0][:70]),
        )
    console.print(table)
    return 0


async def _mcp_exposed(hub: McpHub, server: str) -> list[RemoteTool]:
    from jarvis.tools.mcp.hub import McpError

    try:
        tools = [tool for tool in await hub.start() if tool.server == server]
        entry = hub.servers.get(server)
        if not tools and entry is not None and entry.error:
            raise McpError(f"{server} failed: {entry.error}")
        return tools
    finally:
        await hub.aclose()


def test_calendar(settings: Settings, console: Console) -> int:
    """Download the calendar and count events. Prints counts only, never a title."""
    from datetime import datetime, timedelta

    from jarvis.tools.calendar.feed import Calendar, CalendarError

    calendar = Calendar(settings.calendar)
    now = datetime.now().astimezone()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    try:
        with console.status("Downloading your calendar..."):
            today = asyncio.run(calendar.events(midnight, midnight + timedelta(days=1)))
            week = asyncio.run(calendar.events(midnight, midnight + timedelta(days=7)))
    except CalendarError as exc:
        console.print(f"[red]{escape(str(exc))}[/red]")
        return 1
    feeds = len(Calendar.urls())
    console.print(
        f"[green]Read {feeds} calendar{'s' if feeds > 1 else ''}.[/green] "
        f"{len(today)} event{'' if len(today) == 1 else 's'} today, "
        f"{len(week)} in the next 7 days. "
        'Now ask Jarvis: "what\'s on today?"'
    )
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


def claude_hook(
    settings: Settings, action: str, console: Console, claude_dir: Path | None = None
) -> int:
    """The Claude Code bridge (ADR-051). In "run" mode stdout carries only the hook's reply."""
    from jarvis.bridge import hook

    settings_path = (claude_dir or Path.home() / ".claude") / "settings.json"
    if action == "run":
        file_only_logging(settings.data_dir)
        reply = hook.run_hook(sys.stdin.read(), settings.data_dir)
        if reply:
            sys.stdout.write(reply)
        return 0
    if action == "install":
        hook.install(settings_path, REPO_ROOT)
        console.print(
            "Claude Code now asks you through Jarvis while `jarvis serve` runs "
            "(questions, permissions, and when it is waiting).\n"
            f"[dim]Hooks added to {escape(str(settings_path))}; a backup is next to it. "
            "Undo with: uv run jarvis claude-hook uninstall[/dim]"
        )
        return 0
    if action == "uninstall":
        removed = hook.uninstall(settings_path)
        console.print(
            "Removed Jarvis's hooks." if removed else "Jarvis's hooks were not installed."
        )
        return 0
    running = bridge_running(settings.data_dir)
    if action == "status":
        state = "installed" if hook.installed(settings_path) else "not installed"
        console.print(
            f"Hooks: {state} ({escape(str(settings_path))}). "
            f"Jarvis: {'running' if running else 'not running (start it with jarvis serve)'}."
        )
        return 0
    if not running:  # test
        console.print("[red]Start Jarvis first: uv run jarvis serve[/red]")
        return 2
    event = {
        "hook_event_name": "PreToolUse",
        "tool_name": "AskUserQuestion",
        "cwd": str(REPO_ROOT),
        "tool_input": {
            "questions": [
                {
                    "question": "This is a test from Jarvis. Which color do you like?",
                    "header": "Test",
                    "options": [{"label": "Blue"}, {"label": "Green"}, {"label": "Red"}],
                    "multiSelect": False,
                }
            ]
        },
    }
    console.print("Jarvis is asking now: answer by voice or on the page...")
    reply = hook.run_hook(json.dumps(event), settings.data_dir)
    answers = json.loads(reply)["hookSpecificOutput"]["updatedInput"]["answers"] if reply else {}
    console.print(f"Claude would get: {answers or 'no answer (it would ask you itself)'}")
    return 0


def file_only_logging(data_dir: Path) -> None:
    """Log to the file and nowhere else: Claude Code reads this process's stdout."""
    import logging
    from logging.handlers import RotatingFileHandler

    (data_dir / "logs").mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        data_dir / "logs" / "claude-hook.log", maxBytes=500_000, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


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
