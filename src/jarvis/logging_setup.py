"""Logging: a rotating file under the data folder, and only warnings on the console."""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler

# Libraries that log every request at INFO; their warnings still come through.
NOISY_LOGGERS = (
    "httpx",
    "httpx2",
    "httpcore",
    "openai",
    "primp",
    "ddgs",
    "trafilatura",
    "htmldate",
    "uvicorn",
)


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
    for noisy in NOISY_LOGGERS:
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # yfinance logs its own errors ("possibly delisted") that Jarvis reports in plain words.
    logging.getLogger("yfinance").setLevel(logging.CRITICAL)
    return log_file
