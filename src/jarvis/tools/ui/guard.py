"""Risk rules for generic UI automation (click, type_text, press_keys).

A generic click can press Send or Delete, so these tools ask first except inside apps you list in
`safety.trusted_ui_apps`, and even there a target that looks destructive asks. Some apps are
never trusted, whatever the config says: in a messaging app typing plus Enter sends a message
(send_whatsapp exists so that always reads the message back first), and in a terminal it runs a
command. A few are off limits entirely. This is a heuristic on names, not a guarantee (RISKS.md R6).
"""

from __future__ import annotations

import re

from jarvis.config import SafetySettings
from jarvis.tools.base import Risk
from jarvis.tools.ui.keys import KeyCombo

# Executable names (without .exe, compared case-insensitively).
ALWAYS_ASK = {
    "whatsapp",
    "whatsapp.root",
    "telegram",
    "signal",
    "slack",
    "discord",
    "ms-teams",
    "teams",
    "outlook",
    "olk",
    "thunderbird",
    "windowsterminal",
    "wt",
    "openconsole",
    "conhost",
    "cmd",
    "powershell",
    "pwsh",
    "wsl",
    "mintty",
}
BLOCKED = {
    "regedit": "Registry Editor",
    "mmc": "management consoles (disk management, services, devices)",
    "credentialuibroker": "Windows sign-in prompts",
    "consent": "administrator prompts",
    "keepass": "password managers",
    "keepassxc": "password managers",
    "1password": "password managers",
    "bitwarden": "password managers",
    "lastpass": "password managers",
    "dashlane": "password managers",
}

DESTRUCTIVE = re.compile(
    r"\b(send|delete|remove|erase|discard|don'?t save|uninstall|format|reset|buy|pay|purchase|"
    r"order|checkout|check out|submit|transfer|empty|clear|close|exit|quit|sign out|log ?out|"
    r"restart|shut ?down|overwrite|replace|post|publish|unsubscribe|deactivate)\b",
    re.IGNORECASE,
)
DESTRUCTIVE_KEYS = {
    "Alt+F4",
    "Ctrl+W",
    "Ctrl+Shift+W",
    "Ctrl+Q",
    "Ctrl+F4",
    "Delete",
    "Shift+Delete",
}


def app_ui_risk(app: str, exe: str, safety: SafetySettings) -> tuple[Risk, str | None]:
    """How much permission generic UI actions in this app need, before looking at the target."""
    key = exe.casefold()
    if key in BLOCKED:
        return Risk.BLOCKED, f"UI automation is not allowed in {BLOCKED[key]}"
    if key in ALWAYS_ASK or app.casefold() in ALWAYS_ASK:
        return Risk.CONFIRM, f"{app} can send messages or run commands, so this always asks"
    trusted = {name.casefold() for name in safety.trusted_ui_apps}
    if app.casefold() in trusted:
        return Risk.SAFE, None
    return Risk.CONFIRM, f"{app} is not in safety.trusted_ui_apps"


def target_risk(label: str) -> tuple[Risk, str | None]:
    if DESTRUCTIVE.search(label):
        return Risk.CONFIRM, f"'{label}' looks like it sends, deletes, buys, or closes something"
    return Risk.SAFE, None


def keys_risk(combos: list[KeyCombo]) -> tuple[Risk, str | None]:
    risky = [combo.label for combo in combos if combo.label in DESTRUCTIVE_KEYS]
    if risky:
        return Risk.CONFIRM, f"{risky[0]} can close or delete things"
    return Risk.SAFE, None


def combine(*ratings: tuple[Risk, str | None]) -> tuple[Risk, str | None]:
    """The highest risk, with the reason that goes with it."""
    risk, reason = Risk.SAFE, None
    for level, why in ratings:
        if level.rank > risk.rank:
            risk, reason = level, why
    return risk, reason
