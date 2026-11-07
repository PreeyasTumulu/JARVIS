"""Fail if a tracked file holds personal data: a home folder path, a home network address,
a real-looking Indian phone number, a real email address, or an API key (Phase 31, ADR-102).

Jarvis is built on one person's laptop, and live tests print real names, devices, and
addresses. This keeps them out of the public repo. The obvious fakes the tests and docs use
are allowed below; anything else needs a made-up value instead.

Usage: uv run python scripts/check_personal.py
"""

from __future__ import annotations

import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".ico", ".onnx", ".wav", ".mp3", ".db", ".webp"}
SKIP = {"uv.lock", "check_personal.py"}  # lock hashes look like keys; this file holds the patterns


@dataclass(frozen=True)
class Rule:
    name: str
    pattern: re.Pattern[str]
    allowed: re.Pattern[str] | None = None  # a match that also matches this is a known fake

    def problems(self, line: str) -> list[str]:
        found = []
        for match in self.pattern.finditer(line):
            text = match.group(0)
            if self.allowed is None or not self.allowed.search(text):
                found.append(text)
        return found


RULES = [
    Rule(
        "home folder path",
        re.compile(r"(?i)(?:[A-Z]:[\\/]+Users[\\/]+|/home/|/Users/)([^\\/\s\"'`<>]+)"),
        # Placeholders the docs use, and Windows' own shared folders.
        re.compile(
            r"(?i)[\\/](you|me|user|username|name|example|public|default|<[^>]+>|\{[^}]+\}|%[^%]+%)$"
        ),
    ),
    Rule(
        "a temporary folder of this machine",
        re.compile(r"(?i)AppData[\\/]+Local[\\/]+Temp[\\/]+claude"),
    ),
    Rule(
        "home network address",
        re.compile(
            r"\b(?:192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"
        ),
        # The usual examples: a router at 192.168.1.1, test devices on 192.168.1.x and 10.0.0.x.
        re.compile(r"^(?:192\.168\.1\.\d{1,3}|10\.0\.0\.\d{1,3})$"),
    ),
    Rule(
        "Indian mobile number",
        re.compile(r"(?:\+91|\b91)[ -]?[6-9]\d{4}[ -]?\d{5}\b"),
        # The made-up numbers in tests and docs.
        re.compile(r"98765[ -]?432\d\d|90000[ -]?0000\d|98000[ -]?0000\d"),
    ),
    Rule(
        "email address",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+\b"),
        re.compile(
            r"(?i)@(?:[\w-]+\.)*(?:example|test|invalid|localhost)(?:\.\w+)?$"
            r"|@(?:users\.noreply\.github\.com|anthropic\.com)$|^(?:you|me|your\.name|noreply)@"
        ),
    ),
    Rule(
        "API key or token",
        re.compile(
            r"\b(?:gsk_|sk-or-v1-|sk-ant-|ghp_|gho_|github_pat_|xox[bp]-|AIza)[A-Za-z0-9_-]{16,}"
            r"|\bAC[0-9a-f]{32}\b"
        ),
        re.compile(r"abcdefghij|x{10,}|0{10,}"),  # the fakes the secret tests use
    ),
]


def tracked_files(root: Path) -> list[Path]:
    output = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [root / line for line in output.splitlines() if line]


def scan(text: str) -> list[tuple[int, str, str]]:
    """(line number, rule, the matched text) for each problem in `text`."""
    found = []
    for number, line in enumerate(text.splitlines(), start=1):
        for rule in RULES:
            found.extend((number, rule.name, hit) for hit in rule.problems(line))
    return found


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    problems: list[str] = []
    for path in tracked_files(root):
        if path.suffix.lower() in BINARY_SUFFIXES or path.name in SKIP or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for number, rule, hit in scan(text):
            problems.append(f"{path.relative_to(root)}:{number}: {rule}: {hit}")
    for problem in problems:
        print(problem)
    if problems:
        print(f"\n{len(problems)} possible personal detail(s). Use a made-up value instead.")
        return 1
    print("No personal paths, addresses, numbers, emails, or keys found.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
