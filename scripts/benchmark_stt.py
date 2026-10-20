r"""Benchmark Whisper models on spoken Jarvis commands: word error rate and time per command.

By default the commands are spoken by Piper (the voice Jarvis uses) with light background
noise, which compares models with each other. Your own voice is what counts: --record has you
read the commands once (saved in %LOCALAPPDATA%\Jarvis\stt-test, never in the repo), and
--mine benchmarks on those recordings.

Usage:
    uv run python scripts/benchmark_stt.py
    uv run python scripts/benchmark_stt.py --record     # read 30 commands aloud, once
    uv run python scripts/benchmark_stt.py --mine       # then compare models on your voice
    uv run python scripts/benchmark_stt.py --models small.en base.en --device cuda
"""

from __future__ import annotations

import argparse
import re
import statistics
import time
from datetime import datetime
from pathlib import Path

import numpy as np

from jarvis.config import load_settings
from jarvis.voice.stt import Transcriber
from jarvis.voice.tts.piper_engine import PiperTTS

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = [
    "open notepad",
    "search youtube for lofi music",
    "what's the weather tomorrow in Bangalore",
    "set a timer for ten minutes",
    "message mom that I'll be late",
    "call Ravi",
    "read my notifications",
    "pause the music",
    "next song",
    "any new email",
    "read the second one",
    "reply that I'll send the report tonight",
    "what's on my calendar today",
    "what's my next meeting",
    "am I free on Friday",
    "remember that my manager is Ravi",
    "who is my manager",
    "price of Reliance shares",
    "convert one hundred dollars to rupees",
    "set the volume to thirty",
    "lock my computer",
    "take a screenshot",
    "show the logs of the postgres container",
    "open VS Code",
    "close the calculator",
    "type hello world in Notepad",
    "any open issues on my Jarvis repo on GitHub",
    "think harder about why the Roman empire fell",
    "remind me to call the bank at five",
    "stop",
]
NUMBERS = {"ten": "10", "thirty": "30", "five": "5", "one hundred": "100", "hundred": "100"}


def words(text: str) -> list[str]:
    text = text.casefold().replace("'", "")
    for spoken, digits in NUMBERS.items():
        text = re.sub(rf"\b{spoken}\b", digits, text)
    return re.sub(r"[^\w\s]", " ", text).split()


def wer(reference: str, hypothesis: str) -> float:
    ref, hyp = words(reference), words(hypothesis)
    row = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        previous, row[0] = row[0], i
        for j, h in enumerate(hyp, 1):
            previous, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, previous + (r != h))
    return row[-1] / max(1, len(ref))


def speech(tts: PiperTTS, text: str, rng: np.random.Generator) -> np.ndarray:
    audio, rate = tts.synthesize(text)
    samples = audio.astype(np.float32)
    if rate != 16_000:
        positions = np.linspace(0, len(samples) - 1, int(len(samples) * 16_000 / rate))
        samples = np.interp(positions, np.arange(len(samples)), samples)
    noise = rng.normal(0, np.sqrt(np.mean(samples**2)) / 10, len(samples))  # about 20 dB SNR
    pad = np.zeros(4_000, dtype=np.float32)
    return np.clip(np.concatenate([pad, samples + noise, pad]), -32768, 32767).astype(np.int16)


def record(folder: Path, device: str | int | None) -> None:
    """Record each command from the microphone: Enter to start, Enter to stop."""
    import wave

    import sounddevice as sd

    from jarvis.voice.audio import resolve_input_device

    folder.mkdir(parents=True, exist_ok=True)
    index = resolve_input_device(device)
    print(f"Saving to {folder}. Speak normally, as you would to Jarvis.")
    for number, text in enumerate(COMMANDS, start=1):
        input(f"\n[{number}/{len(COMMANDS)}] Press Enter, then say: {text!r}")
        frames: list[np.ndarray] = []
        with sd.InputStream(
            samplerate=16_000,
            channels=1,
            dtype="int16",
            device=index,
            callback=lambda data, *_, keep=frames: keep.append(data.copy()),
        ):
            input("  ...recording, press Enter when done")
        audio = np.concatenate(frames)[:, 0] if frames else np.zeros(0, dtype=np.int16)
        with wave.open(str(folder / f"{number:02d}.wav"), "wb") as out:
            out.setnchannels(1)
            out.setsampwidth(2)
            out.setframerate(16_000)
            out.writeframes(audio.tobytes())
    print("Done. Now run: uv run python scripts/benchmark_stt.py --mine")


def recorded(folder: Path) -> list[tuple[str, np.ndarray]]:
    import wave

    clips = []
    for number, text in enumerate(COMMANDS, start=1):
        path = folder / f"{number:02d}.wav"
        if path.exists():
            with wave.open(str(path), "rb") as clip:
                clips.append((text, np.frombuffer(clip.readframes(clip.getnframes()), np.int16)))
    if not clips:
        raise SystemExit("No recordings yet: run with --record first.")
    return clips


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", nargs="+", default=["small.en", "base.en", "distil-small.en"])
    parser.add_argument("--device", default="cpu", choices=["cpu", "cuda"])
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "benchmarks" / "stt.md")
    parser.add_argument("--record", action="store_true", help="record your own voice once")
    parser.add_argument("--mine", action="store_true", help="benchmark on your recordings")
    args = parser.parse_args()

    settings = load_settings()
    folder = settings.data_dir / "stt-test"
    if args.record:
        record(folder, settings.voice.input_device)
        return
    if args.mine:
        clips = recorded(folder)
        if args.out == ROOT / "docs" / "benchmarks" / "stt.md":
            args.out = folder / "results.md"  # your voice's results stay with your recordings
    else:
        tts = PiperTTS(settings.tts.piper_voice, settings.models_dir)
        rng = np.random.default_rng(7)
        clips = [(text, speech(tts, text, rng)) for text in COMMANDS]
    rows = []
    for model in args.models:
        compute = "int8" if args.device == "cpu" else "int8_float16"
        cfg = settings.voice.model_copy(
            update={"stt_model": model, "stt_device": args.device, "stt_compute_type": compute}
        )
        stt = Transcriber(cfg, settings.models_dir)
        started = time.perf_counter()
        stt.load()
        load_s = time.perf_counter() - started
        stt.transcribe(clips[0][1])  # warm up
        errors, times, misses = [], [], []
        for text, audio in clips:
            heard = stt.transcribe(audio)
            errors.append(wer(text, heard.text))
            times.append(heard.stt_ms)
            if errors[-1] > 0:
                misses.append(f"{text!r} -> {heard.text!r}")
        rows.append(
            (
                model,
                statistics.mean(errors),
                int(statistics.median(times)),
                max(times),
                load_s,
                misses,
            )
        )
        print(f"{model}: WER {statistics.mean(errors):.1%}, median {statistics.median(times)} ms")

    lines = [
        f"# Speech recognition benchmark ({args.device})",
        "",
        f"Run on {datetime.now():%Y-%m-%d %H:%M}. {len(clips)} Jarvis commands "
        + (
            "in your own voice"
            if args.mine
            else "spoken by Piper with background noise at about 20 dB SNR"
        )
        + ", transcribed with Jarvis's own settings (beam 1, the command hint). Word error rate "
        "counts digits and spelled numbers as equal.",
        "",
        "Regenerate with `uv run python scripts/benchmark_stt.py`.",
        "",
        "| Model | Word error rate | Median time | Slowest | Load |",
        "|---|---|---|---|---|",
    ]
    for model, error, median, slowest, load_s, _ in rows:
        lines.append(f"| `{model}` | {error:.1%} | {median} ms | {slowest} ms | {load_s:.1f} s |")
    for model, *_, misses in rows:
        lines += ["", f"## `{model}` mistakes", ""]
        lines += [f"- {miss}" for miss in misses] or ["None."]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
