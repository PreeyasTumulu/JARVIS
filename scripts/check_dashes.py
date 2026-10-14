"""Fail if any tracked text file contains an em dash or en dash (project style rule).

Usage: uv run python scripts/check_dashes.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

FORBIDDEN = {chr(0x2013): "en dash", chr(0x2014): "em dash"}  # built so this file stays clean
BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".onnx", ".wav", ".mp3", ".db"}


def tracked_files(root: Path) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [root / line for line in output.splitlines() if line]


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    problems: list[str] = []
    for path in tracked_files(root):
        if path.suffix.lower() in BINARY_SUFFIXES or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, line in enumerate(text.splitlines(), start=1):
            for char, label in FORBIDDEN.items():
                if char in line:
                    problems.append(f"{path.relative_to(root)}:{number}: {label}")
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} dash problem(s). Use a hyphen instead.")
        return 1
    print("No em or en dashes found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
