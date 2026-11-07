"""Phase 31: the repo holds no personal data, and the check that keeps it out works (ADR-102).

The real-looking values below are built from pieces, so this file passes the check itself.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "check_personal", ROOT / "scripts" / "check_personal.py"
)
assert _spec is not None
assert _spec.loader is not None
check = importlib.util.module_from_spec(_spec)
sys.modules["check_personal"] = check  # its dataclass looks itself up here
_spec.loader.exec_module(check)


def rules(text: str) -> list[str]:
    return [rule for _, rule, _ in check.scan(text)]


@pytest.mark.parametrize(
    ("text", "rule"),
    [
        ("C:" + "\\Users\\" + "asha\\Documents\\notes.md", "home folder path"),
        ("/home/" + "asha/.ssh", "home folder path"),
        ("phone at 192.168." + "68.20", "home network address"),
        ("server 10.4." + "2.9", "home network address"),
        ("call +91 " + "91234 56789", "Indian mobile number"),
        ("from asha." + "rao@" + "gmail.com", "email address"),
        ("GROQ_API_KEY=gsk_" + "Q7xkP2mW9vLr4TzN8bYc", "API key or token"),
        ("AppData\\Local\\" + "Temp\\claude\\x", "a temporary folder of this machine"),
    ],
)
def test_real_looking_values_are_caught(text: str, rule: str) -> None:
    assert rule in rules(text)


@pytest.mark.parametrize(
    "text",
    [
        "uv run jarvis contacts import C:\\Users\\you\\Downloads\\contacts.vcf",
        'ROUTER = "http://192.168.1.1/"',
        'contacts add "Amma" "+91 98765 43210"',
        "Ravi Kumar <ravi@work.example>",
        'address = "you@gmail.com"',
        "Co-Authored-By: someone <noreply@anthropic.com>",
        "GROQ_API_KEY=gsk_abcdefghijklmnopqrstuvwxyz0123456789",
        "ssh -p 2222 me@192.168.1.20",
    ],
)
def test_the_known_fakes_pass(text: str) -> None:
    assert rules(text) == []


def test_the_repo_is_clean() -> None:
    assert check.main() == 0, "run scripts/check_personal.py to see what it found"
