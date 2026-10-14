from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.cli import build_parser, main


def test_parser_knows_the_commands() -> None:
    parser = build_parser()
    assert parser.parse_args(["chat", "--speak"]).speak is True
    assert parser.parse_args(["ask", "open notepad"]).text == "open notepad"
    assert parser.parse_args(["audit", "--last", "5"]).last == 5


def test_version(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["version"]) == 0
    assert "jarvis" in capsys.readouterr().out


def test_audit_without_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    assert main(["audit"]) == 0
    assert "No audit log yet" in capsys.readouterr().out
