"""Logging: a rotating file under the data folder, and only warnings on the console."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler


def setup_logging(data_dir: Path, *, verbose: bool = False) -> Path:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "jarvis.log"

    file_handler = RotatingFileHandler(
        log_file, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    console_handler = RichHandler(
        level=logging.DEBUG if verbose else logging.WARNING, show_path=False
    )

    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    for noisy in ("httpx", "httpcore", "openai", "primp", "ddgs"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    return log_file
