"""`jarvis serve`: the web UI, with voice and reminders, in one process and one event loop.

The page, the push-to-talk hotkey, "Hey Jarvis", and reminders all drive the same agent, so
everything shows up in every open tab. Confirmations race the page against voice: whichever
answers first wins (ADR-022). The server listens on 127.0.0.1 only.
"""

from __future__ import annotations

import asyncio
import contextlib
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
    from jarvis.voice.channel import VoiceChannel
    from jarvis.voice.session import VoiceSession

HOST = "127.0.0.1"


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
            )
        )
    console.print("[dim]Jarvis stopped.[/dim]")
    return 0


async def _serve(
    runtime: Runtime,
    console: Console,
    voice_channel: VoiceChannel | None,
    *,
    port: int,
    token: str,
    open_browser: bool,
    wake: bool,
) -> None:
    app = runtime.app
    session: VoiceSession | None = None
    hotkeys: HotkeyListener | None = None
    background: list[asyncio.Task[Any]] = []
    try:
        warning = await app.llm.check()
        if warning:
            console.print(f"[yellow]{escape(warning)}[/yellow]")
        if voice_channel is not None:
            session, hotkeys = await _start_voice(app, console, voice_channel, wake=wake)
            if session is not None:
                runtime.voice = session
                background.append(asyncio.create_task(session.run(), name="voice"))
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
        background.append(
            asyncio.create_task(_when_ready(server, url, console, open_browser, runtime))
        )
        await server.serve()
    finally:
        if hotkeys is not None:
            hotkeys.stop()
        for task in background:
            task.cancel()
        await asyncio.gather(*background, return_exceptions=True)
        if session is not None:
            await session.close()
        await app.aclose()


async def _start_voice(
    app: App, console: Console, channel: VoiceChannel, *, wake: bool
) -> tuple[VoiceSession | None, HotkeyListener | None]:
    from jarvis.voice import runner

    session = runner.create_session(app.settings, app, wake_enabled=wake)
    try:
        await runner.prepare(session, app.settings, console)
    except Exception as exc:  # a broken microphone or model must not take the page down
        console.print(
            f"[yellow]Voice could not start ({escape(str(exc))}); the page works without it."
            "[/yellow]"
        )
        return None, None
    channel.attach(session)
    hotkeys = runner.start_hotkeys(app.settings, session, asyncio.get_running_loop(), console)
    return session, hotkeys


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
