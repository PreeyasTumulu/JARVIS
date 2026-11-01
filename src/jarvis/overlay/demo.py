"""`jarvis overlay demo`: the whole effect once, with no microphone, model, or real command."""

from __future__ import annotations

import math
import time

from rich.console import Console

from jarvis.config import Settings
from jarvis.overlay.client import OverlayClient, launch_process
from jarvis.overlay.director import Message

SPOKEN = "open docker and show me the logs"
CONFIRM = 'Send this WhatsApp message to Amma (number ending 1111): "I will be late"'
REPLY = "Docker is open. The postgres container has been up for two hours with no errors."


def _text(heading: str, body: str = "", status: str = "", tone: str = "normal") -> Message:
    return {"t": "text", "heading": heading, "body": body, "status": status, "tone": tone}


def _speak_words(client: OverlayClient, words: str, seconds: float) -> None:
    """Pretend to speak: a moving level, and the words arriving a few at a time."""
    parts = words.split()
    started = time.monotonic()
    while (elapsed := time.monotonic() - started) < seconds:
        beat = abs(math.sin(elapsed * 7.0) * math.sin(elapsed * 2.3 + 1.0))
        client.send({"t": "level", "v": round(0.2 + 0.7 * beat, 3)})
        shown = max(1, round(len(parts) * min(1.0, elapsed / (seconds * 0.85))))
        client.send(_text("Listening", " ".join(parts[:shown])))
        time.sleep(0.08)


def run_demo(settings: Settings, console: Console) -> int:
    cfg = settings.overlay
    config = {
        "mode": cfg.mode,
        "dim": cfg.dim,
        "show_in_captures": cfg.show_in_captures,
        "max_visible_s": cfg.max_visible_s,
    }
    client = OverlayClient(
        config, lambda: launch_process(settings.data_dir / "logs" / "overlay.log")
    )
    client.start()
    console.print("Showing the overlay for about 20 seconds. Nothing is recorded, sent, or run.")
    time.sleep(1.5)  # the process has to start; a running Jarvis keeps it ready
    client.send({"t": "wake"})
    client.send({"t": "state", "state": "listening"})
    client.send(_text("Listening"))
    time.sleep(1.6)
    _speak_words(client, SPOKEN, 3.2)
    client.send({"t": "state", "state": "transcribing"})
    client.send(_text("Got it", SPOKEN))
    time.sleep(0.8)
    client.send({"t": "state", "state": "thinking"})
    client.send(_text("Thinking", SPOKEN, "Running docker_logs"))
    time.sleep(3.4)
    client.send({"t": "state", "state": "speaking"})
    client.send(_text("Jarvis", REPLY))
    time.sleep(4.0)
    client.send({"t": "state", "state": "awaiting_answer"})
    client.send(_text("Say yes or no", CONFIRM, tone="confirm"))
    time.sleep(4.0)
    client.send({"t": "hide", "after": 0.0})
    time.sleep(1.2)
    client.close()
    return 0
