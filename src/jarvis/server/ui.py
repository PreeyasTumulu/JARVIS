"""The chat window: `jarvis serve` serves the page, and Brave or Edge shows it as an app (ADR-103).

The page is `ui/chat.html`, a copy of `ui-demos/chat.html` kept in step by
`scripts/build_ui_demos.py`. Without the meta tag added here it plays its demo; with it, it
connects to this server's WebSocket and shows real turns.

What keeps a website from using the page or its socket:
- the page carries its own UI token, which no other request accepts;
- the WebSocket accepts a browser only when its Origin is exactly this page's address and the
  UI token matches (app.py), and the Host check already defeats DNS rebinding;
- a website cannot read the page (no cross-origin reads) or frame it (`frame-ancestors 'none'`),
  and a request for it from another site (`Sec-Fetch-Site: cross-site` or `same-site`) is refused;
- a nonce lets only the page's own two scripts run (a strict Content-Security-Policy).
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import shutil
import subprocess
import webbrowser
from pathlib import Path

from jarvis.platform.browsers import default_browser, find_brave

log = logging.getLogger(__name__)

PAGE = Path(__file__).with_name("ui") / "chat.html"
LIVE_MARKER = "<!-- jarvis:live -->"
WINDOW_SIZE = "480,800"
EDGE = Path("Microsoft") / "Edge" / "Application" / "msedge.exe"
CHROME = Path("Google") / "Chrome" / "Application" / "chrome.exe"


def ui_token(data_dir: Path) -> str:
    """The chat page's token, kept in the data folder so an open window survives a restart.

    Only this Windows account can read the data folder, as with bridge.json; the token opens
    the WebSocket from the chat page only, never the bridge or /mcp/.
    """
    path = data_dir / "ui_token"
    try:
        token = path.read_text("utf-8").strip()
        if len(token) >= 24:
            return token
    except OSError:
        pass
    token = secrets.token_urlsafe(24)
    path.write_text(token, "utf-8")
    return token


def origins(port: int) -> frozenset[str]:
    """The page's own addresses: the only browser Origins the WebSocket accepts."""
    return frozenset({f"http://127.0.0.1:{port}", f"http://localhost:{port}"})


def url(port: int) -> str:
    return f"http://127.0.0.1:{port}/"


def page(port: int, ui_token: str) -> tuple[str, str]:
    """The page with the live connection details, and the Content-Security-Policy to send."""
    nonce = secrets.token_urlsafe(16)
    html = PAGE.read_text(encoding="utf-8")
    live = json.dumps({"port": port, "token": ui_token})
    meta = f"<meta name=\"jarvis-live\" content='{live}'>"
    if LIVE_MARKER not in html:
        raise RuntimeError("the chat page has no live marker")
    html = html.replace(LIVE_MARKER, meta, 1).replace("<script>", f'<script nonce="{nonce}">')
    sockets = " ".join(f"ws://{origin.removeprefix('http://')}" for origin in sorted(origins(port)))
    policy = "; ".join(
        [
            "default-src 'none'",
            f"script-src 'nonce-{nonce}'",
            "style-src 'unsafe-inline'",  # the page's own style block and the orb's transforms
            "img-src data:",
            f"connect-src {sockets}",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
        ]
    )
    return html, policy


def browser_command(target: str) -> list[str] | None:
    """Brave, Edge, or Chrome in app mode: its own window, no tabs or address bar."""
    choice = default_browser()
    found: Path | None = None
    if choice in (None, "brave"):
        found = find_brave()
    if found is None and choice == "chrome":
        found = _installed(CHROME)
    if found is None:
        found = _installed(EDGE) or _installed(CHROME)
    if found is None:
        return None
    return [str(found), f"--app={target}", f"--window-size={WINDOW_SIZE}"]


def _installed(relative: Path) -> Path | None:
    for var in ("PROGRAMFILES(X86)", "PROGRAMFILES", "LOCALAPPDATA"):
        root = os.environ.get(var)
        if root and (candidate := Path(root) / relative).is_file():
            return candidate
    which = shutil.which(relative.name)
    return Path(which) if which else None


def running_port(data_dir: Path) -> int | None:
    """The port of the `jarvis serve` running for this account, or None."""
    from jarvis.bridge.service import bridge_file, bridge_running

    if not bridge_running(data_dir):
        return None
    try:
        return int(json.loads(bridge_file(data_dir).read_text("utf-8"))["port"])
    except (OSError, ValueError, KeyError):
        return None


def open_window(port: int) -> str:
    """Open the chat window; which browser showed it."""
    target = url(port)
    command = browser_command(target)
    if command is None:
        webbrowser.open(target)
        return "your browser"
    subprocess.Popen(command, close_fds=True)
    log.info("Opened the chat window with %s", Path(command[0]).stem)
    return Path(command[0]).stem
