"""What one `jarvis serve` process shares: the app, the browser hub, and (optionally) voice.

Browser tabs, voice, and reminders all talk to the same agent, so a command typed in the page and
one spoken aloud land in the same conversation, and every tab sees both.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any

from jarvis import __version__
from jarvis.app import App
from jarvis.server.hub import Client, Message, WebHub
from jarvis.tools.messaging.contacts import ContactError

if TYPE_CHECKING:
    from jarvis.bridge.service import BridgeService
    from jarvis.voice.session import VoiceSession

log = logging.getLogger(__name__)

MAX_COMMAND_CHARS = 2000
HISTORY_TURNS = 20
AUDIT_ROWS = 50
BUSY = "Jarvis is still working on the last command. Press Stop to cancel it."
MAX_NAME_CHARS = 80
MAX_ALIASES = 10
MAX_VCARD_CHARS = 2_000_000


class Runtime:
    def __init__(self, app: App, hub: WebHub, voice: VoiceSession | None = None) -> None:
        self.app = app
        self.hub = hub
        self.voice = voice
        self.bridge: BridgeService | None = None
        self._web_turn: asyncio.Task[Any] | None = None
        app.bus.subscribe(hub.on_event)

    @property
    def busy(self) -> bool:
        return self.app.agent.busy or (self._web_turn is not None and not self._web_turn.done())

    def hello(self) -> Message:
        """Everything a tab needs when it connects: who we are, recent turns, open questions."""
        settings = self.app.settings
        history = [
            {
                "ts": row["ts"],
                "source": row["source"],
                "text": row["input_text"],
                "reply": row["response_text"],
                "status": row["status"],
            }
            for row in self.app.history.recent(HISTORY_TURNS)
        ]
        return {
            "type": "hello",
            "version": __version__,
            "model": self.app.llm.model,
            "busy": self.busy,
            "voice": {
                "enabled": self.voice is not None,
                "wake_word": bool(self.voice and self.voice.wake_enabled),
                "state": self.voice.state if self.voice else "off",
                "ptt_hotkey": settings.voice.ptt_hotkey,
                "stop_hotkey": settings.voice.stop_hotkey,
            },
            "history": history,
            "open": self.hub.open_items(),
        }

    async def handle(self, client: Client, message: Message) -> None:
        """One request from a tab. Anything unexpected gets an error message, never a crash."""
        kind = message.get("type")
        if kind == "command":
            self._command(client, str(message.get("text") or ""))
        elif kind == "stop":
            await self.stop()
        elif kind == "confirm":
            # Only an explicit true approves; anything else is a no.
            self.hub.resolve(str(message.get("request_id")), message.get("approved") is True)
        elif kind == "answer":
            self.hub.answer(str(message.get("question_id")), str(message.get("text") or ""))
        elif kind == "mic":
            self._mic(client, message.get("on") is True)
        elif kind == "audit":
            client.send({"type": "audit", "rows": self.app.audit.recent(AUDIT_ROWS)})
        elif kind == "contacts":
            client.send(self.contacts_message())
        elif kind in ("contact_add", "contact_remove", "contact_import"):
            self._change_contacts(client, kind, message)
        else:
            client.send({"type": "error", "message": f"Unknown request type {kind!r}."})

    def _command(self, client: Client, raw: str) -> None:
        text = raw.strip()
        if not text:
            return
        if len(text) > MAX_COMMAND_CHARS:
            client.send({"type": "error", "message": "That command is too long."})
            return
        if self.busy:
            client.send({"type": "error", "message": BUSY})
            return
        self._web_turn = asyncio.create_task(
            self.app.agent.run_turn(text, source="web"), name="web-turn"
        )

    def contacts_message(self, note: str = "", error: bool = False, added: bool = False) -> Message:
        book = self.app.services.contacts
        return {
            "type": "contacts",
            "contacts": [contact.as_dict() for contact in book.all()],
            "note": note,
            "error": error,
            "added": added,
        }

    def _change_contacts(self, client: Client, kind: str, message: Message) -> None:
        """Contacts are yours to edit from the page; the model has no tool that changes them."""
        book = self.app.services.contacts
        try:
            if kind == "contact_add":
                aliases = message.get("aliases") or []
                if not isinstance(aliases, list) or len(aliases) > MAX_ALIASES:
                    raise ContactError(f"Give at most {MAX_ALIASES} other names.")
                contact = book.add(
                    str(message.get("name") or "")[:MAX_NAME_CHARS],
                    str(message.get("phone") or "")[:MAX_NAME_CHARS],
                    [str(alias)[:MAX_NAME_CHARS] for alias in aliases],
                )
                note = f"Added {contact.name}."
            elif kind == "contact_remove":
                note = f"Removed {book.remove(str(message.get('id') or '')).name}."
            else:
                text = str(message.get("text") or "")
                if len(text) > MAX_VCARD_CHARS:
                    raise ContactError("That file is too large.")
                result = book.import_vcard(text)
                note = f"Imported {len(result.added)} contacts."
                if result.skipped:
                    note += f" Skipped {len(result.skipped)}: " + "; ".join(result.skipped[:5])
        except ContactError as exc:
            client.send(self.contacts_message(str(exc), error=True))
            return
        self.hub.broadcast(self.contacts_message(note, added=kind == "contact_add"))

    def _mic(self, client: Client, on: bool) -> None:
        """The page's talk button works like holding the push-to-talk hotkey."""
        if self.voice is None:
            client.send({"type": "error", "message": "Voice is off in this session."})
            return
        if self.voice.muted:
            client.send(
                {"type": "error", "message": "The microphone is off. Turn it on from the tray."}
            )
            return
        self.voice.on_hotkey("ptt", "down" if on else "up")

    async def stop(self) -> None:
        """The Stop button: cancel the command, speech, listening, and open questions."""
        if self.voice is not None:
            await self.voice.stop()
        else:
            self.app.agent.cancel()
            await self.app.services.tts.stop()
