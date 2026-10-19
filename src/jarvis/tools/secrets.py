"""Hide secrets (API keys, tokens, passwords, private keys) in text a tool reads.

The file tools refuse files that look like secrets by name (.env, *.pem). Text copied to the
clipboard, shown in a window, logged by a container, or written inside an ordinary file can
still hold one; this keeps the value out of the model's context and the audit log. It is a
safety net, not a guarantee: a secret with no recognizable shape gets through.
"""

from __future__ import annotations

import re

HIDDEN = "[hidden]"

# Values with a recognizable shape, wherever they appear.
_TOKENS = re.compile(
    r"""
    -----BEGIN[A-Z ]*PRIVATE\ KEY-----.*?-----END[A-Z ]*PRIVATE\ KEY-----   # PEM private keys
    | \bsk-or-v1-[A-Za-z0-9]{20,}                 # OpenRouter
    | \bsk-ant-[A-Za-z0-9_-]{20,}                 # Anthropic
    | \bsk-(?:proj-)?[A-Za-z0-9_-]{20,}           # OpenAI style
    | \bgsk_[A-Za-z0-9]{20,}                      # Groq
    | \bgh[pousr]_[A-Za-z0-9]{30,}                # GitHub tokens
    | \bgithub_pat_[A-Za-z0-9_]{30,}
    | \bAKIA[0-9A-Z]{16}\b                        # AWS access key id
    | \bAIza[0-9A-Za-z_-]{35}\b                   # Google API key
    | \bxox[abprs]-[A-Za-z0-9-]{10,}              # Slack
    | \beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}   # JWTs
    """,
    re.VERBOSE | re.DOTALL,
)

# NAME=value or "name": "value" where the name says it is a secret.
_ASSIGNMENT = re.compile(
    r"""(?ix)
    (?P<name>\b[\w.-]*(?:api[_-]?key|secret|token|passw(?:or)?d|pwd|private[_-]?key|
        access[_-]?key|client[_-]?secret|auth)[\w.-]*["']?)
    (?P<sep>\s*[:=]\s*["']?)
    (?P<value>[^\s"',;]{4,})
    """
)


def redact_secrets(text: str) -> tuple[str, int]:
    """The text with secret values replaced by [hidden], and how many were hidden."""
    count = 0

    def token(_match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        return HIDDEN

    def assignment(match: re.Match[str]) -> str:
        nonlocal count
        if match.group("value") == HIDDEN:
            return match.group(0)
        count += 1
        return f"{match.group('name')}{match.group('sep')}{HIDDEN}"

    text = _TOKENS.sub(token, text)
    text = _ASSIGNMENT.sub(assignment, text)
    return text, count


def note(count: int) -> str:
    """What the model is told when something was hidden."""
    noun = (
        "value that looks like a secret was" if count == 1 else "values that look like secrets were"
    )
    return f"{count} {noun} hidden as {HIDDEN}; do not guess or ask for it."


def hide_secrets(data: dict[str, object], field: str) -> dict[str, object]:
    """Redact data[field] in place (a tool result's text) and add a note when anything went."""
    value = data.get(field)
    if isinstance(value, str):
        data[field], count = redact_secrets(value)
        if count:
            data["secrets_hidden"] = note(count)
    return data
