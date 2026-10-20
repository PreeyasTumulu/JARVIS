"""`jarvis voice` and `jarvis setup-voice`: wire microphone, models, hotkeys, and the agent."""

from __future__ import annotations

import asyncio
import time

import numpy as np
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
    resolve_input_device,
    rms,
)
from jarvis.voice.channel import VoiceChannel
from jarvis.voice.dictation import Inserter
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
            runner.run(app.start_background(session.announce))
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
    """Push-to-talk, stop, and dictation hotkeys from config. Raises ValueError for a bad one."""
    cfg = settings.voice
    bindings = {"ptt": parse_hotkey(cfg.ptt_hotkey), "stop": parse_hotkey(cfg.stop_hotkey)}
    if settings.dictation.enabled:
        bindings["dictate"] = parse_hotkey(settings.dictation.hotkey)
    return bindings


def wake_detector(settings: Settings) -> WakeWordDetector:
    cfg = settings.voice
    return WakeWordDetector(
        cfg.wake_word,
        settings.models_dir,
        verifier=cfg.wake_verifier,
        verifier_floor=cfg.wake_verifier_floor,
    )


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
        wake=wake_detector(settings) if wake_enabled else None,
        vad=SileroVAD(settings.models_dir, cfg.wake_word) if wake_enabled else None,
        dictation=Inserter(settings.dictation) if settings.dictation.enabled else None,
    )


async def prepare(session: VoiceSession, settings: Settings, console: Console) -> None:
    """Load every speech model up front and warn about a silent microphone.

    Raises ValueError first, before any model loads, when the configured microphone is not
    there (at login it can show up late; `jarvis serve` then tries again).
    """
    await asyncio.to_thread(resolve_input_device, settings.voice.input_device)
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
    """Register the hotkeys system wide; events reach the session on its loop."""
    bindings = hotkey_bindings(settings)

    def on_hotkey(name: str, phase: str) -> None:  # runs on the hotkey thread
        loop.call_soon_threadsafe(session.on_hotkey, name, phase)

    hotkeys = HotkeyListener(bindings, on_hotkey, hold={"ptt", "dictate"})
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
    if settings.dictation.enabled:
        lines.append(
            f"[bold]Hold {escape(settings.dictation.hotkey)}[/bold] to dictate into any app."
        )
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


def wake_test(settings: Settings, console: Console, *, seconds: float) -> int:
    """Print the microphone level and the wake word score twice a second, nothing else.

    Nothing is recorded or transcribed. Use it to check that "Hey Jarvis" scores above
    wake_threshold from where you sit, and to pick a threshold for config/local.toml.
    """
    cfg = settings.voice
    detector = wake_detector(settings)
    with console.status("Loading the wake word model..."):
        detector.load()
    trained = " with the verifier trained on your voice" if detector.verified else ""
    console.print(
        f'Say "Hey Jarvis" a few times{trained}. Threshold {cfg.wake_threshold:.2f} '
        f"(wake_threshold under \\[voice]). "
        f"Microphone: {escape(str(cfg.input_device or 'default'))}."
    )

    async def measure() -> int:
        mic = MicStream(cfg.input_device)
        await mic.start()
        hits = 0
        try:
            end = time.monotonic() + seconds
            window: list[float] = []
            levels: list[float] = []
            peaks: list[float] = []  # the best score of each half second that had one
            while time.monotonic() < end:
                frame = await asyncio.wait_for(mic.read(), timeout=3)
                if frame is None:
                    break
                window.append(await asyncio.to_thread(detector.score, frame))
                levels.append(rms(frame))
                if len(window) == 6:  # about half a second
                    best, level = max(window), max(levels)
                    peaks.append(best)
                    bar = "#" * min(40, int(level / 50))
                    mark = "  [bold green]WAKE[/bold green]" if best >= cfg.wake_threshold else ""
                    console.print(f"level {level:6.0f} {bar:<40} score {best:.2f}{mark}")
                    if best >= cfg.wake_threshold:
                        hits += 1
                        detector.reset()
                    window, levels = [], []
        except TimeoutError:
            console.print("[red]The microphone sent no audio for 3 seconds.[/red]")
            return 1
        finally:
            await mic.stop()
        console.print(f"{hits} wake word detection(s) in {seconds:.0f} s.")
        console.print(wake_advice(peaks, cfg.wake_threshold, detector.verified))
        return 0

    return asyncio.run(measure())


def wake_advice(peaks: list[float], threshold: float, verified: bool) -> str:
    """What to do after a wake test, from the half-second peaks."""
    tops = sorted(peaks, reverse=True)
    near = [p for p in tops if threshold * 0.4 <= p < threshold]
    if not tops or tops[0] < 0.1:
        return "The wake word never registered: check the microphone (level) and say it clearly."
    if tops[0] >= threshold:
        return "It works. If it also wakes up on its own, raise wake_threshold a little."
    best = ", ".join(f"{p:.2f}" for p in tops[:5])
    if verified:
        return (
            f"Your best scores were {best}, below {threshold:.2f}. Train again in your usual spot "
            "(uv run jarvis voice --train-wake)."
        )
    tip = (
        f'Your "Hey Jarvis" scored up to {best}, below the threshold {threshold:.2f}. The fix: '
        "teach it your voice (about two minutes): uv run jarvis voice --train-wake"
    )
    if near:
        tip += (
            f". A quick stopgap: wake_threshold = {max(0.2, round(near[0] * 0.8, 2))} under [voice]"
        )
    return tip + "."


def train_wake(settings: Settings, console: Console) -> int:
    """Record your voice and train the wake word verifier (ADR-064)."""
    import sounddevice as sd

    from jarvis.voice import wake_training as training

    cfg = settings.voice
    index = resolve_input_device(cfg.input_device)
    folder = training.training_dir(settings.data_dir)

    def record(seconds: float) -> np.ndarray:
        audio = sd.rec(
            int(seconds * 16_000), samplerate=16_000, channels=1, dtype="int16", device=index
        )
        sd.wait()
        return np.asarray(audio)[:, 0]

    console.print(
        'Jarvis will learn your voice from 8 recordings of "Hey Jarvis" and about 25 seconds '
        f"of other speech. They stay in {escape(str(folder))}. Sit where you usually sit."
    )
    positives = []
    for number in range(1, 9):
        input(f'[{number}/8] Press Enter, then say "Hey Jarvis" once (2 seconds)... ')
        clip = record(2.0)
        positives.append(clip)
        training.save_wav(folder / "positive" / f"{number:02d}.wav", clip)
    console.print(
        f"\nNow read this aloud at a normal pace (20 seconds):\n\n  {training.NEGATIVE_PASSAGE}\n"
    )
    input("Press Enter and start reading... ")
    speech = record(20.0)
    input("Now press Enter and stay quiet for 5 seconds (the room's own noise)... ")
    quiet = record(5.0)
    negatives = training.split(speech) + training.split(quiet)
    for number, clip in enumerate(negatives, start=1):
        training.save_wav(folder / "negative" / f"{number:02d}.wav", clip)

    with console.status("Training on your voice..."):
        try:
            report = training.train(settings.models_dir, cfg.wake_word, positives, negatives)
        except ValueError as exc:
            console.print(f"[red]{escape(str(exc))}[/red]")
            return 1
    scores = ", ".join(f"{s:.2f}" for s in report.positive_scores)
    console.print(
        f'Trained on {report.positive_examples} moments of your "Hey Jarvis" and '
        f"{report.negative_examples} of other sound.\nYour recordings now score: {scores} "
        f"({report.caught} of 8 above 0.50). Other speech peaks at {report.negative_best:.2f}."
    )
    if report.negative_best >= cfg.wake_threshold:
        console.print(
            "[yellow]Other speech also scores high: it may wake up on its own. Train again with "
            'clearer "Hey Jarvis" recordings.[/yellow]'
        )
    console.print("Check it live: uv run jarvis voice --wake-test 30")
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
