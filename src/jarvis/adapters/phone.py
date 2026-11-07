"""Your own phone, for free: KDE Connect on the same Wi-Fi first, an ntfy push anywhere else.

Phase 29 looked at real phone calls first (docs/RESEARCH.md section 8): every way for Jarvis to
speak in a call costs money per minute, and Indian numbers need a registered business, so
Jarvis reaches you this way instead (ADR-098).

- KDE Connect (`kdeconnect-cli`, from the KDE Connect app): ring the phone loudly even on
  silent, show a notification, send a file, a link, text, or the clipboard. It talks to the
  phone over your own network with TLS, so nothing leaves it. It needs the phone paired once.
- ntfy: a push through `[phone] ntfy_server` to `[phone] ntfy_topic`, when the phone is not on
  this network. Anyone who knows a topic name can read it, so it carries short alerts only;
  files never go this way.

Every call has a timeout, and logs never show message text.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

import httpx

from jarvis.config import PhoneSettings

log = logging.getLogger(__name__)

CLI_TIMEOUT_S = 15.0
SHARE_TIMEOUT_S = 120.0  # a large file over Wi-Fi
MAX_TEXT_CHARS = 1000
KDE = "kdeconnect"
NTFY = "ntfy"
# "- Test Phone: 0a1b2c on 192.168.1.50 via LAN (paired and reachable)"
_LINE = re.compile(r"^- (?P<name>.+?): (?P<id>[\w{}-]+)\b.*\((?P<state>[^()]*)\)\s*$")

Runner = Callable[[list[str], float], Awaitable[str]]


class PhoneError(Exception):
    """The phone could not be reached; the message says why and what to do."""


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    paired: bool
    reachable: bool

    @property
    def usable(self) -> bool:
        return self.paired and self.reachable


def parse_devices(text: str) -> list[Device]:
    """`kdeconnect-cli --list-devices`. The Windows build's `--list-available` printed nothing
    for a reachable phone in the live test, so the full list is read instead."""
    found = []
    for line in text.splitlines():
        match = _LINE.match(line.strip())
        if match is None:
            continue
        state = match["state"].casefold()
        found.append(
            Device(
                id=match["id"],
                name=match["name"].strip(),
                paired="paired" in state and "unpaired" not in state,
                reachable="reachable" in state and "unreachable" not in state,
            )
        )
    return found


def clip(text: str) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= MAX_TEXT_CHARS else flat[: MAX_TEXT_CHARS - 3] + "..."


class Phone:
    def __init__(
        self,
        settings: PhoneSettings,
        *,
        http: httpx.AsyncClient | None = None,
        runner: Runner | None = None,
        ntfy_token: str | None = None,
    ) -> None:
        self._settings = settings
        self._http = http
        self._runner = runner or self._run
        self._token = ntfy_token if ntfy_token is not None else os.environ.get("NTFY_TOKEN")

    # KDE Connect

    async def _run(self, args: list[str], timeout_s: float) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                self._settings.kdeconnect_cli,
                *args,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except (FileNotFoundError, PermissionError):
            raise PhoneError(
                "KDE Connect is not installed. Get it from the Microsoft Store and pair your "
                "phone (SETUP.md 5s)."
            ) from None
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
        except TimeoutError:
            proc.kill()
            raise PhoneError(f"KDE Connect gave no answer in {timeout_s:.0f} seconds.") from None
        if proc.returncode != 0:
            message = (err or out).decode("utf-8", "replace").strip().splitlines()
            raise PhoneError(f"KDE Connect failed: {(message or ['no details'])[0][:200]}")
        return out.decode("utf-8", "replace")

    @property
    def kde_enabled(self) -> bool:
        return self._settings.kdeconnect

    async def devices(self) -> list[Device]:
        if not self.kde_enabled:
            return []
        return parse_devices(await self._runner(["--list-devices"], CLI_TIMEOUT_S))

    async def device(self) -> Device | None:
        """The phone to use when it is paired and on this network, else None."""
        try:
            devices = await self.devices()
        except PhoneError as exc:
            log.info("No phone through KDE Connect: %s", exc)
            return None
        return self._choose(devices)

    def _choose(self, devices: list[Device]) -> Device | None:
        wanted = self._settings.device.strip().casefold()
        if wanted:
            devices = [d for d in devices if wanted in (d.id.casefold(), d.name.casefold())]
        usable = [d for d in devices if d.usable]
        return usable[0] if len(usable) == 1 or (wanted and usable) else None

    async def why_not(self) -> str:
        """What stands between Jarvis and the phone, said so the user can fix it."""
        if not self.kde_enabled:
            kde = "KDE Connect is off ([phone] kdeconnect)"
        else:
            try:
                devices = await self.devices()
            except PhoneError as exc:
                devices, kde = [], str(exc).rstrip(".")
            else:
                kde = self._kde_problem(devices)
        if self.ntfy_ready:
            return f"{kde}."
        return f"{kde}. Set [phone] ntfy_topic to reach it away from home (SETUP.md 5s)."

    def _kde_problem(self, devices: list[Device]) -> str:
        wanted = self._settings.device.strip()
        if wanted:
            mine = [d for d in devices if wanted.casefold() in (d.id.casefold(), d.name.casefold())]
            if not mine:
                return f"KDE Connect knows no device called {wanted}"
            devices = mine
        if not devices:
            return "No phone is paired in KDE Connect"
        if len([d for d in devices if d.usable]) > 1:
            names = ", ".join(d.name for d in devices if d.usable)
            return f"Several phones are paired ({names}); set [phone] device to one of them"
        phone = devices[0]
        if not phone.paired:
            return (
                f"{phone.name} is on the Wi-Fi but not paired: open KDE Connect on the PC, "
                "choose it, press Pair, and accept on the phone"
            )
        return f"{phone.name} is not on this Wi-Fi or KDE Connect is closed on it"

    async def ring(self, device: Device) -> None:
        await self._runner(["--device", device.id, "--ring"], CLI_TIMEOUT_S)

    async def ping(self, device: Device, text: str) -> None:
        await self._runner(["--device", device.id, "--ping-msg", clip(text)], CLI_TIMEOUT_S)

    async def share(self, device: Device, target: str) -> None:
        """A file path or a web link: the phone saves the file or opens the link."""
        await self._runner(["--device", device.id, "--share", target], SHARE_TIMEOUT_S)

    async def share_text(self, device: Device, text: str) -> None:
        await self._runner(["--device", device.id, "--share-text", text], CLI_TIMEOUT_S)

    async def send_clipboard(self, device: Device) -> None:
        await self._runner(["--device", device.id, "--send-clipboard"], CLI_TIMEOUT_S)

    # ntfy

    @property
    def ntfy_ready(self) -> bool:
        return bool(self._settings.ntfy_alerts and self._settings.ntfy_topic.strip())

    async def push(self, title: str, message: str, *, priority: int = 4) -> None:
        if not self.ntfy_ready:
            raise PhoneError("No ntfy topic is set ([phone] ntfy_topic).")
        body = {
            "topic": self._settings.ntfy_topic.strip(),
            "title": clip(title)[:120],
            "message": clip(message),
            "priority": priority,
            "tags": ["robot"],
        }
        headers = {"Authorization": f"Bearer {self._token}"} if self._token else {}
        http = self._http or httpx.AsyncClient(timeout=CLI_TIMEOUT_S)
        try:
            response = await http.post(
                self._settings.ntfy_server.rstrip("/"), json=body, headers=headers
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise PhoneError(f"The ntfy push failed ({type(exc).__name__}).") from None
        finally:
            if self._http is None:
                await http.aclose()

    # Both

    async def route(self) -> tuple[str, Device | None]:
        """How a short alert would reach the phone right now: KDE Connect, else ntfy."""
        device = await self.device()
        if device is not None:
            return KDE, device
        if self.ntfy_ready:
            return NTFY, None
        raise PhoneError(await self.why_not())

    async def alert(self, text: str, *, ring: bool = False, title: str = "Jarvis") -> str:
        """Tell the phone `text` (and ring it); which way it went. KDE Connect first, ntfy if
        the phone is away. Used by reminders and the Claude Code bridge, which own the text."""
        device = await self.device()
        if device is not None:
            try:
                await self.ping(device, f"{title}: {text}")
                if ring:
                    await self.ring(device)
                return KDE
            except PhoneError as exc:
                log.info("KDE Connect alert failed, trying ntfy: %s", exc)
        if self.ntfy_ready:
            await self.push(title, text, priority=5 if ring else 4)
            return NTFY
        raise PhoneError(await self.why_not())
