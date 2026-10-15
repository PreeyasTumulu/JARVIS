"""`jarvis voice` and `jarvis setup-voice`: wire microphone, models, hotkeys, and the agent."""

from __future__ import annotations

import asyncio
import time

from rich.console import Console
from rich.markup import escape

from jarvis.app import App, build_app
from jarvis.config import Settings
from jarvis.console import ConsoleChannel, ConsoleRenderer
from jarvis.core.channel import FirstAnswerChannel
from jarvis.platform.hotkeys import Hotkey, HotkeyListener, parse_hotkey
from jarvis.voice.audio import (
    SILENT_RMS,
    AudioPlayer,
    Earcons,
    MicStream,
    list_input_devices,
    microphone_level,
)
from jarvis.voice.channel import VoiceChannel
from jarvis.voice.models import ensure_piper_voice, ensure_wake_models
from jarvis.voice.session import VoiceSession
from jarvis.voice.stt import Transcriber
from jarvis.voice.wake import SileroVAD, WakeWordDetector


def run_voice(settings: Settings, console: Console, *, wake: bool, verbose: bool) -> int:
    cfg = settings.voice
    wake_enabled = wake or cfg.wake_word_enabled
    try:
        hotkey_bindings(settings)
    except ValueError as exc:
        console.print(f"[red]{escape(str(exc))}. Fix [voice] in config/local.toml.[/red]")
        return 2

    voice_channel = VoiceChannel()
    channel = FirstAnswerChannel(voice_channel, ConsoleChannel(console))
    with asyncio.Runner() as runner:
        app = build_app(settings, channel)
        app.bus.subscribe(ConsoleRenderer(console, verbose=verbose))
        session = create_session(settings, app, wake_enabled=wake_enabled)
        voice_channel.attach(session)
        hotkeys: HotkeyListener | None = None
        try:
            warning = runner.run(app.llm.check())
            if warning:
                console.print(f"[yellow]{escape(warning)}[/yellow]")
            runner.run(prepare(session, settings, console))
            hotkeys = start_hotkeys(settings, session, runner.get_loop(), console)
            _print_banner(console, settings, wake_enabled)
            runner.run(app.start_reminders(session.announce))
            runner.run(session.run())
        except KeyboardInterrupt:
            pass
        finally:
            if hotkeys is not None:
                hotkeys.stop()
            runner.run(session.close())
            summary = session.latency_summary()
            if summary:
                console.print(f"[dim]{summary}[/dim]")
            runner.run(app.aclose())
    return 0


def hotkey_bindings(settings: Settings) -> dict[str, Hotkey]:
    """The push-to-talk and stop hotkeys from config. Raises ValueError for a bad one."""
    cfg = settings.voice
    return {"ptt": parse_hotkey(cfg.ptt_hotkey), "stop": parse_hotkey(cfg.stop_hotkey)}


def create_session(settings: Settings, app: App, *, wake_enabled: bool) -> VoiceSession:
    cfg = settings.voice
    return VoiceSession(
        agent=app.agent,
        bus=app.bus,
        settings=settings,
        mic=MicStream(cfg.input_device),
        stt=Transcriber(cfg, settings.models_dir),
        tts=app.services.tts,
        cues=Earcons(AudioPlayer(), enabled=cfg.earcons),
        wake=WakeWordDetector(cfg.wake_word, settings.models_dir) if wake_enabled else None,
        vad=SileroVAD(settings.models_dir, cfg.wake_word) if wake_enabled else None,
    )


async def prepare(session: VoiceSession, settings: Settings, console: Console) -> None:
    """Load every speech model up front and warn about a silent microphone."""
    started = time.perf_counter()
    with console.status("Loading speech models (the first run downloads them)..."):
        await session.load()
    console.print(f"[dim]Models ready in {time.perf_counter() - started:.1f}s[/dim]")
    await _check_microphone(settings, console)


def start_hotkeys(
    settings: Settings,
    session: VoiceSession,
    loop: asyncio.AbstractEventLoop,
    console: Console,
) -> HotkeyListener:
    """Register push-to-talk and stop system wide; events reach the session on its loop."""
    bindings = hotkey_bindings(settings)

    def on_hotkey(name: str, phase: str) -> None:  # runs on the hotkey thread
        loop.call_soon_threadsafe(session.on_hotkey, name, phase)

    hotkeys = HotkeyListener(bindings, on_hotkey, hold={"ptt"})
    hotkeys.start()
    for name in hotkeys.failed:
        console.print(
            f"[yellow]Could not register {escape(bindings[name].text)} "
            f"({name}); another app may own it. Change it under [voice] in "
            "config/local.toml.[/yellow]"
        )
    return hotkeys


def _print_banner(console: Console, settings: Settings, wake_enabled: bool) -> None:
    cfg = settings.voice
    lines = [
        f"[bold]Hold {escape(cfg.ptt_hotkey)}[/bold], speak after the beep, then release.",
        f'[bold]{escape(cfg.stop_hotkey)}[/bold] or saying "stop" cancels what Jarvis is doing.',
    ]
    if wake_enabled:
        lines.insert(1, 'Or say [bold]"Hey Jarvis"[/bold], wait for the beep, and speak.')
    lines.append("Confirmations: say yes or no, or press y or n here. Ctrl+C quits.")
    console.print("\n".join(lines))


def setup_voice(settings: Settings, console: Console) -> int:
    cfg = settings.voice
    with console.status("Downloading speech-to-text model..."):
        Transcriber(cfg, settings.models_dir).load()
    with console.status("Downloading Piper voice..."):
        try:
            ensure_piper_voice(settings.models_dir, settings.tts.piper_voice)
        except ImportError:
            console.print("[yellow]Piper is not installed; the SAPI voice will be used.[/yellow]")
    with console.status("Downloading wake word and VAD models..."):
        ensure_wake_models(settings.models_dir, cfg.wake_word)
    console.print(f"Voice models are ready in {escape(str(settings.models_dir))}")
    return 0


def list_devices(console: Console) -> int:
    for index, name, is_default in list_input_devices():
        marker = "  [green](Windows default)[/green]" if is_default else ""
        console.print(f"{index:>3}  {escape(name)}{marker}")
    console.print(
        "[dim]To pick one, set input_device under \\[voice] in config/local.toml to part of its "
        'name, for example input_device = "Microphone Array".[/dim]'
    )
    return 0


async def _check_microphone(settings: Settings, console: Console) -> None:
    device = settings.voice.input_device
    try:
        level = await microphone_level(device)
    except Exception as exc:
        console.print(f"[red]Could not open the microphone: {escape(str(exc))}[/red]")
        return
    if level < SILENT_RMS:
        name = escape(str(device or "the Windows default microphone"))
        console.print(
            f"[yellow]{name} is sending pure silence (muted, or a virtual device). "
            "Run `uv run jarvis voice --list-devices` and set input_device under \\[voice] "
            "in config/local.toml.[/yellow]"
        )
