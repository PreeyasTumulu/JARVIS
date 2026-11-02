"""Reach your phone when nobody answers at the PC (ADR-052). Off unless bridge.phone is set.

ntfy: a push to the free ntfy app (Android, iOS), urgent priority, with an answer button per
option (ntfy allows three). Pressing one publishes to a reply topic Jarvis polls. Anyone who
knows a topic name can read and post to it, so permissions are only asked this way when an
access token protects the topics (NTFY_TOKEN in .env); questions are asked either way.

twilio: a real call. A Twilio Studio flow (docs/twilio-ask-flow.json) says the question and
collects a keypad digit or a spoken answer; Jarvis reads the result from the flow's execution,
so no public web address is needed. Calls cost money; the keys live in .env.

Either way the question text leaves this computer (to ntfy or Twilio), which is why it is off
by default. Nothing here sees Jarvis's own private data: only what Claude Code asked.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import time
from typing import Any

import httpx

from jarvis.bridge.answers import NUMBERS
from jarvis.bridge.service import Asker, BridgeRequest, page_question, spoken_question
from jarvis.config import Settings

log = logging.getLogger(__name__)

POLL_S = 2.0
NTFY_BUTTONS = 3
CALL_WAIT_S = 120.0


def phone_asker(settings: Settings, http: httpx.AsyncClient | None = None) -> Asker | None:
    """The configured way to ask your phone, or None when it is off or not set up."""
    method = settings.bridge.phone
    phone = settings.phone
    if method == "ntfy":
        if not phone.ntfy_topic:
            log.warning("bridge.phone is ntfy but phone.ntfy_topic is empty; phone is off")
            return None
        return NtfyAsker(phone.ntfy_server, phone.ntfy_topic, os.environ.get("NTFY_TOKEN"), http)
    if method == "twilio":
        sid, token = os.environ.get("TWILIO_ACCOUNT_SID"), os.environ.get("TWILIO_AUTH_TOKEN")
        if not (sid and token and phone.number and phone.twilio_from and phone.twilio_flow_sid):
            log.warning("bridge.phone is twilio but its settings or .env keys are missing")
            return None
        return TwilioAsker(sid, token, phone.twilio_flow_sid, phone.twilio_from, phone.number, http)
    return None


class NtfyAsker:
    def __init__(
        self,
        server: str,
        topic: str,
        token: str | None,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._server = server.rstrip("/")
        self._topic = topic
        self._replies = f"{topic}-answers"
        self._token = token
        self._http = http or httpx.AsyncClient(timeout=15)

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._token}"} if self._token else {}

    async def __call__(self, request: BridgeRequest) -> str | None:
        if request.kind == "permission" and not self._token:
            log.info("A permission is not sent to an unprotected ntfy topic")
            return None
        nonce = secrets.token_hex(6)
        question, options = page_question(request)
        buttons = [
            {
                "action": "http",
                "label": option[:40],
                "url": f"{self._server}/{self._replies}",
                "method": "POST",
                "headers": self._headers(),
                "body": f"{nonce}:{index}",
                "clear": True,
            }
            for index, option in enumerate(options[:NTFY_BUTTONS])
        ]
        since = int(time.time())
        message = {
            "topic": self._topic,
            "title": "Claude needs you",
            "message": question,
            "priority": 5,
            "tags": ["robot"],
            "actions": buttons,
        }
        response = await self._http.post(self._server, json=message, headers=self._headers())
        response.raise_for_status()
        while True:
            await asyncio.sleep(POLL_S)
            answer = await self._poll(nonce, since, options)
            if answer is not None:
                return answer

    async def _poll(self, nonce: str, since: int, options: list[str]) -> str | None:
        url = f"{self._server}/{self._replies}/json"
        response = await self._http.get(
            url, params={"poll": "1", "since": str(since)}, headers=self._headers()
        )
        response.raise_for_status()
        for line in response.text.splitlines():
            try:
                body = str(json.loads(line).get("message") or "")
            except (json.JSONDecodeError, AttributeError):
                continue
            tag, _, index = body.partition(":")
            if secrets.compare_digest(tag, nonce) and index.isdigit():
                position = int(index)
                if 0 <= position < len(options):
                    return options[position]
        return None


class TwilioAsker:
    STUDIO = "https://studio.twilio.com/v2/Flows"

    def __init__(
        self,
        account_sid: str,
        auth_token: str,
        flow_sid: str,
        from_number: str,
        to_number: str,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self._auth = (account_sid, auth_token)
        self._flow = flow_sid
        self._from = from_number
        self._to = to_number
        self._http = http or httpx.AsyncClient(timeout=20)

    async def __call__(self, request: BridgeRequest) -> str | None:
        question, options = page_question(request)
        if request.kind == "permission":
            prompt = f"{spoken_question(request)} Press 1 to allow, 2 to deny."
        else:
            listed = " ".join(f"Press {i + 1} for {o}." for i, o in enumerate(options[:9]))
            prompt = f"{question}. {listed}"
        execution = await self._http.post(
            f"{self.STUDIO}/{self._flow}/Executions",
            auth=self._auth,
            data={"To": self._to, "From": self._from, "Parameters": json.dumps({"q": prompt})},
        )
        execution.raise_for_status()
        sid = str(execution.json()["sid"])
        deadline = time.monotonic() + CALL_WAIT_S
        while time.monotonic() < deadline:
            await asyncio.sleep(POLL_S)
            heard = await self._heard(sid)
            if heard is not None:
                return self._as_option(heard, options)
        return None

    async def _heard(self, execution_sid: str) -> str | None:
        response = await self._http.get(
            f"{self.STUDIO}/{self._flow}/Executions/{execution_sid}/Context", auth=self._auth
        )
        response.raise_for_status()
        widgets: dict[str, Any] = (response.json().get("context") or {}).get("widgets") or {}
        gathered = widgets.get("ask") or {}
        return gathered.get("Digits") or gathered.get("SpeechResult") or None

    @staticmethod
    def _as_option(heard: str, options: list[str]) -> str:
        """A keypad digit picks an option by number; speech is matched like a voice answer."""
        word = heard.strip().casefold().rstrip(".")
        number = int(word) if word.isdigit() else NUMBERS.get(word)
        if number is not None and 1 <= number <= len(options):
            return options[number - 1]
        return heard
