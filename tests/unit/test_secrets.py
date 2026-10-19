"""Secrets in text a tool reads are hidden before the model or the audit log sees them."""

from __future__ import annotations

import pytest

from jarvis.tools.secrets import HIDDEN, redact_secrets
from tests.conftest import FakeDesktop, MakeApp, reply

# Shaped like real keys, but made up.
GROQ = "gsk_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4"
OPENROUTER = "sk-or-v1-" + "0123456789abcdef0123456789abcdef"
GITHUB = "ghp_" + "abcdefghijklmnopqrstuvwxyz0123456789"


@pytest.mark.parametrize(
    "text",
    [
        f"GROQ_API_KEY={GROQ}",
        f"export OPENROUTER_API_KEY='{OPENROUTER}'",
        f'{{"api_key": "{GROQ}"}}',
        "password: hunter2hunter2",
        "DB_PASSWORD = s3cr3t-value",
        f"token {GITHUB} in the middle of a sentence",
        "-----BEGIN RSA PRIVATE KEY-----\nMIIEow\n-----END RSA PRIVATE KEY-----",
        "AKIAABCDEFGHIJKLMNOP",
    ],
)
def test_secret_values_are_hidden(text: str) -> None:
    hidden, count = redact_secrets(text)
    assert count >= 1
    assert HIDDEN in hidden
    for secret in (GROQ, OPENROUTER, GITHUB, "hunter2hunter2", "s3cr3t-value", "MIIEow"):
        assert secret not in hidden


@pytest.mark.parametrize(
    "text",
    [
        "The auth flow sends a token to the server.",
        "FINNHUB_API_KEY=",  # empty: nothing to hide
        "Reset your password from the settings page.",
        "skip-this is not a key",
    ],
)
def test_ordinary_text_is_left_alone(text: str) -> None:
    assert redact_secrets(text) == (text, 0)


async def test_the_clipboard_hides_a_copied_env_file(
    make_app: MakeApp, desktop: FakeDesktop
) -> None:
    desktop.clipboard = f"# keys\nGROQ_API_KEY={GROQ}\nFINNHUB_API_KEY=\n"
    h = make_app([reply("", ("clipboard_read", {})), reply("It is a list of API keys.")])
    await h.app.agent.run_turn("what is on my clipboard")
    sent = str(h.llm.requests)
    assert GROQ not in sent
    assert "GROQ_API_KEY=[hidden]" in sent
    assert GROQ not in str(h.audit())
