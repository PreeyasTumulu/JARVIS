"""The terminal channel, its live log, the model client's errors, and CLI commands that need no
model or Windows feature."""

from __future__ import annotations

import io
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import httpx
import openai
import pytest
from rich.console import Console

from jarvis import console as console_module
from jarvis.cli import main
from jarvis.config import ProviderSettings
from jarvis.console import ConsoleChannel, ConsoleRenderer
from jarvis.core.channel import ConfirmationRequest
from jarvis.core.events import (
    AssistantMessage,
    ModelReplied,
    ToolCallFinished,
    ToolCallStarted,
    VoiceStateChanged,
)
from jarvis.llm.client import LLMClient
from jarvis.llm.types import LLMError


def _console() -> tuple[Console, io.StringIO]:
    out = io.StringIO()
    return Console(file=out, width=200, force_terminal=False), out


def _request() -> ConfirmationRequest:
    return ConfirmationRequest("r1", "open_app", "Open [Paint]", "digest", "not on the list", 30)


def _typed(monkeypatch: pytest.MonkeyPatch, answer: str | BaseException) -> None:
    async def read_line() -> str:
        if isinstance(answer, BaseException):
            raise answer
        return answer

    monkeypatch.setattr(console_module, "read_line", read_line)


@pytest.mark.parametrize(
    ("typed", "approved"),
    [("y", True), ("YES ", True), ("n", False), ("", False), ("sure", False)],
)
async def test_only_a_clear_yes_approves(
    monkeypatch: pytest.MonkeyPatch, typed: str, approved: bool
) -> None:
    console, out = _console()
    _typed(monkeypatch, typed)
    assert await ConsoleChannel(console).confirm(_request()) is approved
    assert "Open [Paint]" in out.getvalue()  # shown as text, never as markup


async def test_closed_input_means_no(monkeypatch: pytest.MonkeyPatch) -> None:
    console, _ = _console()
    _typed(monkeypatch, EOFError())
    assert await ConsoleChannel(console).confirm(_request()) is False


@pytest.mark.parametrize(
    ("typed", "answer"), [("2", "SQLite"), ("9", "9"), (" other ", "other"), ("", "")]
)
async def test_questions_take_a_number_or_words(
    monkeypatch: pytest.MonkeyPatch, typed: str, answer: str
) -> None:
    console, out = _console()
    _typed(monkeypatch, typed)
    assert await ConsoleChannel(console).ask("Which?", ["PostgreSQL", "SQLite"]) == answer
    assert "2. SQLite" in out.getvalue()


def test_the_log_shows_each_step_as_text() -> None:
    console, out = _console()
    render = ConsoleRenderer(console)
    render(ModelReplied("t", "hermes", 1500, 1))
    render(ToolCallStarted("t", "c", "open_app", {"name": "[red]paint"}, "safe"))
    render(ToolCallFinished("t", "c", "open_app", "auto", True, "Opened", 12))
    render(ToolCallFinished("t", "c", "open_app", "denied", False, "No", 3))
    render(AssistantMessage("t", "All [done]"))
    render(VoiceStateChanged("listening"))
    text = out.getvalue()
    for piece in ("hermes 1.5s", "1 tool call", "[red]paint", "Opened", "All [done]", "listening"):
        assert piece in text


# The model client's errors


class Refuses:
    def __init__(self, error: Exception) -> None:
        self.error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    async def create(self, **_: Any) -> Any:
        raise self.error


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "http://x/v1"))


@pytest.mark.parametrize(
    ("error", "says"),
    [
        (openai.APIConnectionError(request=httpx.Request("POST", "http://x/v1")), "Ollama"),
        (openai.NotFoundError("no", response=_response(404), body=None), "not found"),
        (openai.InternalServerError("no", response=_response(500), body=None), "(500)"),
    ],
)
async def test_model_errors_are_explained(error: Exception, says: str) -> None:
    provider = ProviderSettings(base_url="http://x/v1", model="m")
    client = LLMClient(provider, client=Refuses(error))  # type: ignore[arg-type]
    with pytest.raises(LLMError, match=said(says)):
        await client.complete([{"role": "user", "content": "hi"}])


def said(text: str) -> str:
    import re

    return re.escape(text)


async def test_a_bare_json_reply_becomes_a_call() -> None:
    message = SimpleNamespace(
        content='{"function": "reply_email", "arguments": {"message": "Ravi"}}', tool_calls=None
    )
    response = SimpleNamespace(choices=[SimpleNamespace(message=message)], model="m", usage=None)

    class Answers:
        chat = SimpleNamespace(completions=SimpleNamespace(create=None))

        def __init__(self) -> None:
            async def create(**_: Any) -> Any:
                return response

            self.chat = SimpleNamespace(completions=SimpleNamespace(create=create))

    provider = ProviderSettings(base_url="http://x/v1", model="m")
    reply = await LLMClient(provider, client=Answers()).complete([])  # type: ignore[arg-type]
    assert [call.name for call in reply.tool_calls] == ["reply_email"]
    assert reply.text == ""
    assert reply.parsed_from_text


# Commands


@pytest.fixture
def data_folder(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    return tmp_path


@pytest.mark.usefixtures("data_folder")
def test_contacts_from_start_to_end(capsys: pytest.CaptureFixture[str], tmp_path: Path) -> None:
    assert main(["contacts", "add", "Test Person", "+919800000000", "--alias", "tester"]) == 0
    assert "Added Test Person" in capsys.readouterr().out

    assert main(["contacts", "alias", "Test Person", "testy"]) == 0
    assert "testy" in capsys.readouterr().out

    assert main(["contacts"]) == 0
    listed = capsys.readouterr().out
    assert "Test Person" in listed
    assert "1 contacts" in listed

    assert main(["contacts", "unalias", "Test Person", "testy"]) == 0
    capsys.readouterr()

    card = tmp_path / "people.vcf"
    card.write_text(
        "BEGIN:VCARD\nVERSION:3.0\nFN:Other Person\nTEL:+919800000001\nEND:VCARD\n",
        encoding="utf-8",
    )
    assert main(["contacts", "import", str(card)]) == 0
    assert "Imported 1" in capsys.readouterr().out

    assert main(["contacts", "remove", "Test Person"]) == 0
    assert "Removed Test Person" in capsys.readouterr().out


@pytest.mark.usefixtures("data_folder")
def test_a_contacts_mistake_is_explained_not_raised(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["contacts", "remove", "Nobody At All"]) == 1
    assert capsys.readouterr().out.strip()


@pytest.mark.usefixtures("data_folder")
def test_the_audit_log_prints_what_was_recorded(capsys: pytest.CaptureFixture[str]) -> None:
    from jarvis.config import default_data_dir
    from jarvis.storage.db import Database
    from jarvis.storage.repositories import AuditEntry, AuditLog

    db = Database(default_data_dir() / "jarvis.db")
    AuditLog(db).record(AuditEntry("s", "t", "open_app", "auto", True, args={"name": "paint"}))
    db.close()
    assert main(["audit", "--last", "5"]) == 0
    assert "open_app" in capsys.readouterr().out
