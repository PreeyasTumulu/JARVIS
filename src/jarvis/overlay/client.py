"""Runs the overlay process and sends it messages. Nothing here can slow or stop the assistant.

`send` never blocks: messages wait in a short queue for a writer thread, and they are dropped when
the process is stuck. If the process dies it is restarted a few times, and then voice simply goes
on without the effect.
"""

from __future__ import annotations

import contextlib
import json
import logging
import queue
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import IO, Any

from jarvis.config import Settings
from jarvis.core.events import EventBus
from jarvis.overlay import EXIT_NO_GRAPHICS
from jarvis.overlay.director import Director, Message

log = logging.getLogger(__name__)

QUEUE_SIZE = 256
MAX_RESTARTS = 3
RESTART_WAIT_S = 2.0

Launch = Callable[[], "subprocess.Popen[bytes]"]


class OverlayClient:
    def __init__(self, config: dict[str, Any], launch: Launch) -> None:
        self._config = config
        self._launch = launch
        self._queue: queue.Queue[Message | None] = queue.Queue(QUEUE_SIZE)
        self._thread: threading.Thread | None = None
        self._process: subprocess.Popen[bytes] | None = None
        self._closing = False

    def start(self) -> None:
        self._thread = threading.Thread(target=self._write_loop, name="overlay", daemon=True)
        self._thread.start()

    def send(self, message: Message) -> None:
        try:
            self._queue.put_nowait(message)
        except queue.Full:
            log.debug("Overlay queue is full; dropped a %s message", message.get("t"))

    def close(self) -> None:
        self._closing = True
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(None)
        if self._process is not None and self._process.stdin is not None:
            with contextlib.suppress(OSError):
                self._process.stdin.close()

    def _write_loop(self) -> None:
        restarts = 0
        while not self._closing and restarts <= MAX_RESTARTS:
            try:
                self._process = self._launch()
                assert self._process.stdin is not None
                self._write(self._process.stdin, self._config)
                self._pump(self._process.stdin)
            except (OSError, ValueError) as exc:
                log.warning("The overlay process stopped: %s", exc)
            if self._closing:
                return
            code = self._process.poll() if self._process is not None else None
            if code == EXIT_NO_GRAPHICS:
                log.warning("This computer cannot show the overlay; voice works without it")
                return
            restarts += 1
            time.sleep(RESTART_WAIT_S)
        if not self._closing:
            log.warning("The overlay kept stopping; voice goes on without it")

    def _pump(self, stdin: IO[bytes]) -> None:
        while True:
            message = self._queue.get()
            if message is None:
                return
            self._write(stdin, message)

    @staticmethod
    def _write(stdin: IO[bytes], message: Message) -> None:
        stdin.write(json.dumps(message, ensure_ascii=False).encode("utf-8") + b"\n")
        stdin.flush()


def launch_process(log_path: Path) -> subprocess.Popen[bytes]:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with log_path.open("ab") as stderr:
        return subprocess.Popen(
            [sys.executable, "-m", "jarvis.overlay"],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=stderr,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )


def start_overlay(settings: Settings, bus: EventBus) -> OverlayClient | None:
    """Start the overlay when it is enabled, listening to the bus. None when it is off."""
    cfg = settings.overlay
    if not cfg.enabled:
        return None
    config = {
        "mode": cfg.mode,
        "dim": cfg.dim,
        "show_in_captures": cfg.show_in_captures,
        "max_visible_s": cfg.max_visible_s,
    }
    log_path = settings.data_dir / "logs" / "overlay.log"
    client = OverlayClient(config, lambda: launch_process(log_path))
    client.start()
    bus.subscribe(Director(client.send).on_event)
    return client
