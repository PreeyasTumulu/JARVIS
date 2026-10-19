"""`jarvis serve`: the web UI, with voice and reminders, in one process and one event loop.

The page, the push-to-talk hotkey, "Hey Jarvis", and reminders all drive the same agent, so
everything shows up in every open tab. Confirmations race the page against voice: whichever
answers first wins (ADR-022). The server listens on 127.0.0.1 only.
"""

from __future__ import annotations

import asyncio
import contextlib
import faulthandler
import logging
import secrets
import socket
import webbrowser
from typing import TYPE_CHECKING, Any

import uvicorn
from rich.console import Console
from rich.markup import escape

from jarvis import __version__
from jarvis.app import App, build_app
from jarvis.config import Settings
from jarvis.console import ConsoleRenderer
from jarvis.core.channel import FirstAnswerChannel, UserChannel
from jarvis.server.app import create_server
from jarvis.server.hub import WebChannel, WebHub
from jarvis.server.runtime import Runtime

if TYPE_CHECKING:
    from jarvis.platform.hotkeys import HotkeyListener
    from jarvis.tray import Tray
    from jarvis.voice.channel import VoiceChannel
    from jarvis.voice.session import VoiceSession

HOST = "127.0.0.1"
VOICE_RETRY_S = (10.0, 20.0, 40.0, 60.0, 120.0)  # then every two minutes
STARTUP_HANG_S = 300  # no page after this long: write every thread's stack to the log folder
log = logging.getLogger(__name__)


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((HOST, port))
        except OSError:
            return False
    return True


def run_serve(
    settings: Settings,
    console: Console,
    *,
    port: int,
    open_browser: bool,
    voice: bool,
    wake: bool,
    verbose: bool,
    tray: bool = False,
) -> int:
    if not port_free(port):
        console.print(
            f"[red]Port {port} is in use (is Jarvis already running?). "
            "Pick another with --port or [server] port in config/local.toml.[/red]"
        )
        return 2

    voice_channel: VoiceChannel | None = None
    if voice:
        try:
            from jarvis.voice.channel import VoiceChannel
            from jarvis.voice.runner import hotkey_bindings

            hotkey_bindings(settings)
            voice_channel = VoiceChannel()
        except ImportError:
            console.print(
                "[yellow]Voice support is not installed, so the page runs without it. "
                "Install it with: uv sync --extra voice --extra piper[/yellow]"
            )
        except ValueError as exc:
            console.print(f"[red]{escape(str(exc))}. Fix [voice] in config/local.toml.[/red]")
            return 2

    hub = WebHub()
    channels: list[UserChannel] = [WebChannel(hub)]
    if voice_channel is not None:
        channels.append(voice_channel)
    app = build_app(settings, FirstAnswerChannel(*channels))
    app.bus.subscribe(ConsoleRenderer(console, verbose=verbose))
    runtime = Runtime(app, hub)
    token = secrets.token_urlsafe(24)
    hang_report = _arm_hang_report(settings)
    with contextlib.suppress(KeyboardInterrupt):
        asyncio.run(
            _serve(
                runtime,
                console,
                voice_channel,
                port=port,
                token=token,
                open_browser=open_browser,
                wake=wake or settings.voice.wake_word_enabled,
                tray=tray,
            )
        )
    faulthandler.cancel_dump_traceback_later()
    hang_report.close()
    console.print("[dim]Jarvis stopped.[/dim]")
    return 0


def _arm_hang_report(settings: Settings) -> Any:
    """If startup never reaches the page (started at login, with no console to look at),
    write where every thread is stuck to logs/startup-hang.txt."""
    path = settings.data_dir / "logs" / "startup-hang.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    report = path.open("w", encoding="utf-8")  # open until Jarvis stops
    faulthandler.dump_traceback_later(STARTUP_HANG_S, file=report)
    return report


async def _serve(
    runtime: Runtime,
    console: Console,
    voice_channel: VoiceChannel | None,
    *,
    port: int,
    token: str,
    open_browser: bool,
    wake: bool,
    tray: bool = False,
) -> None:
    app = runtime.app
    voice = _Voice(runtime, console, voice_channel, wake=wake) if voice_channel else None
    icon: Tray | None = None
    background: list[asyncio.Task[Any]] = []
    try:
        warning = await app.llm.check()
        if warning:
            console.print(f"[yellow]{escape(warning)}[/yellow]")
        voice_ready = await voice.start() if voice is not None else False
        session = voice.session if voice is not None else None
        await app.start_background(session.announce if session else _speaker(app, console))

        config = uvicorn.Config(
            create_server(runtime, token=token, port=port),
            host=HOST,
            port=port,
            log_config=None,  # Jarvis's own logging setup stays in charge
            access_log=False,
            lifespan="off",
        )
        server = uvicorn.Server(config)
        url = f"http://{HOST}:{port}/?token={token}"
        if tray:
            icon = _start_tray(runtime, server, url, session)
        if voice is not None:
            voice.tray = icon
            if not voice_ready:
                background.append(asyncio.create_task(voice.keep_trying(), name="voice-retry"))
        background.append(
            asyncio.create_task(_when_ready(server, url, console, open_browser, runtime))
        )
        await server.serve()
    finally:
        if icon is not None:
            icon.close()
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        if voice is not None:
            await voice.close()
        await app.aclose()


class _Voice:
    """Starts voice, and keeps trying in the background when it cannot start yet.

    At login the desktop comes up before the audio devices (and sometimes the network) are
    ready, so the first attempt can fail. Every failure is logged, because a Jarvis started at
    login has no console to print to.
    """

    def __init__(
        self, runtime: Runtime, console: Console, channel: VoiceChannel, *, wake: bool
    ) -> None:
        self.runtime = runtime
        self.console = console
        self.channel = channel
        self.wake = wake
        self.session: VoiceSession | None = None
        self.tray: Tray | None = None
        self._hotkeys: HotkeyListener | None = None
        self._task: asyncio.Task[None] | None = None
        self._retry: asyncio.Task[None] | None = None
        self._closing = False

    async def start(self) -> bool:
        session, hotkeys = await _start_voice(
            self.runtime.app, self.console, self.channel, wake=self.wake
        )
        if session is None:
            return False
        self.session, self._hotkeys = session, hotkeys
        self.runtime.voice = session
        self._task = asyncio.create_task(session.run(), name="voice")
        self._task.add_done_callback(self._voice_ended)
        if self.tray is not None:
            self.tray.attach_voice(session.set_muted)
            self.tray.show(session.state)
        return True

    async def keep_trying(self) -> None:
        from jarvis.voice.audio import refresh_devices

        for attempt in range(1, 10_000):
            if self.tray is not None:
                self.tray.show("voice_retry")
            await asyncio.sleep(VOICE_RETRY_S[min(attempt, len(VOICE_RETRY_S)) - 1])
            with contextlib.suppress(Exception):
                await asyncio.to_thread(refresh_devices)  # a microphone that appeared since
            if await self.start():
                log.info("Voice started after %d retries", attempt)
                self.console.print("[green]Voice is ready.[/green]")
                return

    def _voice_ended(self, task: asyncio.Task[None]) -> None:
        """The voice loop crashed (the microphone vanished): log it and start over."""
        if task.cancelled() or task.exception() is None or self._closing:
            return
        log.error("Voice stopped working; starting it again", exc_info=task.exception())
        if self._hotkeys is not None:
            self._hotkeys.stop()
        self.session = self._hotkeys = None
        self.runtime.voice = None
        self._retry = asyncio.create_task(self.keep_trying(), name="voice-retry")

    async def close(self) -> None:
        self._closing = True
        if self._retry is not None:
            self._retry.cancel()
        if self._hotkeys is not None:
            self._hotkeys.stop()
        if self._task is not None:
            self._task.cancel()
            await asyncio.gather(self._task, return_exceptions=True)
        if self.session is not None:
            await self.session.close()


async def _start_voice(
    app: App, console: Console, channel: VoiceChannel, *, wake: bool
) -> tuple[VoiceSession | None, HotkeyListener | None]:
    from jarvis.voice import runner

    session = runner.create_session(app.settings, app, wake_enabled=wake)
    try:
        await runner.prepare(session, app.settings, console)
    except Exception as exc:  # a broken microphone or model must not take the page down
        log.warning("Voice could not start: %s", exc, exc_info=True)
        console.print(
            f"[yellow]Voice could not start ({escape(str(exc))}); the page works without it."
            "[/yellow]"
        )
        return None, None
    channel.attach(session)
    hotkeys = runner.start_hotkeys(app.settings, session, asyncio.get_running_loop(), console)
    return session, hotkeys


def _start_tray(
    runtime: Runtime, server: uvicorn.Server, url: str, session: VoiceSession | None
) -> Tray | None:
    try:
        from jarvis.tray import Tray
    except ImportError:
        return None

    def quit_jarvis() -> None:
        server.should_exit = True

    icon = Tray(
        loop=asyncio.get_running_loop(),
        url=lambda: url,
        stop=runtime.stop,
        quit=quit_jarvis,
        set_muted=session.set_muted if session is not None else None,
    )
    try:
        icon.start()
    except Exception as exc:  # no tray (a session without a desktop) must not stop Jarvis
        log.warning("The tray icon could not start: %s", exc)
        return None
    runtime.app.bus.subscribe(icon.on_event)
    if session is not None:
        icon.show(session.state)
    return icon


def _speaker(app: App, console: Console) -> Any:
    async def speak(text: str) -> None:
        try:
            await app.services.tts.speak(text)
        except RuntimeError as exc:
            console.print(f"[yellow]{escape(str(exc))}[/yellow]")

    return speak


async def _when_ready(
    server: uvicorn.Server, url: str, console: Console, open_browser: bool, runtime: Runtime
) -> None:
    while not server.started:  # noqa: ASYNC110 (uvicorn exposes no event for this)
        await asyncio.sleep(0.05)
    faulthandler.cancel_dump_traceback_later()
    log.info("Jarvis %s is ready on port %s", __version__, server.config.port)
    lines = [
        f"[bold]Jarvis {__version__}[/bold] is running at [link={url}]{escape(url)}[/link]",
        "[dim]The link carries a one-time token; it changes every time Jarvis starts.[/dim]",
    ]
    voice = runtime.voice
    if voice is not None:
        cfg = runtime.app.settings.voice
        talk = f"Hold {escape(cfg.ptt_hotkey)} or use the mic button to talk"
        if voice.wake_enabled:
            talk += ', or say "Hey Jarvis"'
        lines.append(f"{talk}. {escape(cfg.stop_hotkey)} stops.")
    lines.append("Ctrl+C here quits.")
    console.print("\n".join(lines))
    if open_browser:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(webbrowser.open, url)
