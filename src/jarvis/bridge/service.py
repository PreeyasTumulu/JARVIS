"""The Claude Code bridge inside `jarvis serve`: ask you, wait for your answer, hand it back.

The hook (`jarvis claude-hook`, run by Claude Code) posts what Claude wants to the local server;
this asks through the same channels as Jarvis's own confirmations (voice and every open page,
first answer wins), so "Claude asks: which framework? One, React. Two, Vue." can be answered
by saying "two" or by clicking. Nothing here goes through a model. No answer within
bridge.answer_timeout_s means no decision, and Claude Code asks you itself as usual.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import secrets
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from jarvis.bridge.answers import match_options, yes_or_no
from jarvis.config import BridgeSettings

log = logging.getLogger(__name__)

Kind = Literal["question", "permission", "notify"]
Asker = Callable[["BridgeRequest"], Awaitable[str | None]]  # one way to reach you
SPOKEN_OPTIONS = 6
NUMBER_WORDS = ("one", "two", "three", "four", "five", "six")


@dataclass(frozen=True)
class BridgeRequest:
    kind: Kind
    text: str  # the question, the permission ("run npm test"), or the notice
    options: list[str] = field(default_factory=list)
    multi: bool = False
    project: str = ""  # the folder Claude works in, said so you know which session asks

    @classmethod
    def parse(cls, data: dict[str, Any]) -> BridgeRequest:
        kind = data.get("kind")
        if kind not in ("question", "permission", "notify"):
            raise ValueError("kind must be question, permission, or notify")
        text = " ".join(str(data.get("text") or "").split())
        if not text:
            raise ValueError("text is required")
        options = [" ".join(str(o).split()) for o in data.get("options") or []][:12]
        return cls(
            kind=kind,
            text=text[:600],
            options=[o for o in options if o],
            multi=bool(data.get("multi")),
            project=str(data.get("project") or "")[:80],
        )


def spoken_question(request: BridgeRequest) -> str:
    """What voice says. Options are numbered so "two" is enough of an answer."""
    where = f" in {request.project}" if request.project else ""
    if request.kind == "permission":
        return f"Claude{where} wants to {request.text}. Allow it? Say yes or no."
    options = request.options[:SPOKEN_OPTIONS]
    numbered = ". ".join(f"{NUMBER_WORDS[i]}, {o}" for i, o in enumerate(options))
    pick = "Say the numbers" if request.multi else "Say the number or the name"
    return f"Claude{where} asks: {request.text} {numbered}. {pick}."


def page_question(request: BridgeRequest) -> tuple[str, list[str]]:
    """What the page shows, with a button per option."""
    where = f" ({request.project})" if request.project else ""
    if request.kind == "permission":
        return f"Claude{where} wants to {request.text}.", ["Allow", "Deny"]
    return f"Claude{where} asks: {request.text}", list(request.options)


class BridgeService:
    def __init__(
        self,
        settings: BridgeSettings,
        askers: Sequence[Asker],
        announce: Callable[[str], Awaitable[None]],
        phone: Asker | None = None,
    ) -> None:
        self._settings = settings
        self._askers = list(askers)
        self._announce = announce
        self._phone = phone
        self._lock = asyncio.Lock()  # one question at a time: you can only answer one

    async def handle(self, request: BridgeRequest) -> dict[str, Any]:
        """{"answer": label} for a question, {"allow": bool} for a permission, {} otherwise."""
        cfg = self._settings
        if request.kind == "notify":
            if cfg.announce:
                await self._announce(request.text)
            return {}
        if request.kind == "question" and not cfg.questions:
            return {}
        if request.kind == "permission" and not cfg.permissions:
            return {}
        async with self._lock:
            return await self._decide(request)

    async def _decide(self, request: BridgeRequest) -> dict[str, Any]:
        """Race every way to reach you; an empty or unclear answer keeps the others waiting."""
        tasks: set[asyncio.Future[str | None]] = {
            asyncio.ensure_future(ask(request)) for ask in self._askers
        }
        if self._phone is not None:
            tasks.add(asyncio.ensure_future(self._phone_after_delay(request)))
        everything = set(tasks)
        try:
            async with asyncio.timeout(self._settings.answer_timeout_s):
                while tasks:
                    done, tasks = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    for task in done:
                        decision = self._read(request, task)
                        if decision:
                            return decision
        except TimeoutError:
            log.info("Nobody answered Claude's %s in time", request.kind)
        finally:
            for task in everything:
                if not task.done():
                    task.cancel()
            await asyncio.gather(*everything, return_exceptions=True)
        return {}

    @staticmethod
    def _read(request: BridgeRequest, task: asyncio.Future[str | None]) -> dict[str, Any]:
        if task.cancelled():
            return {}
        if task.exception() is not None:
            log.info("A way to reach you dropped out: %r", task.exception())
            return {}
        reply = task.result() or ""
        if request.kind == "permission":
            verdict = yes_or_no(reply)
            return {} if verdict is None else {"allow": verdict}
        answer = match_options(reply, request.options, multi=request.multi) if reply else None
        return {} if answer is None else {"answer": answer}

    async def _phone_after_delay(self, request: BridgeRequest) -> str | None:
        assert self._phone is not None
        await asyncio.sleep(self._settings.escalate_after_s)
        return await self._phone(request)


# Where the hook finds the running Jarvis. Written when `jarvis serve` starts, removed when
# it stops; only your Windows account can read your data folder.
def bridge_file(data_dir: Path) -> Path:
    return data_dir / "bridge.json"


def publish_address(data_dir: Path, port: int) -> str:
    token = secrets.token_urlsafe(24)
    path = bridge_file(data_dir)
    path.write_text(json.dumps({"port": port, "token": token, "pid": os.getpid()}), "utf-8")
    return token


def bridge_running(data_dir: Path) -> bool:
    """Whether a Jarvis is listening at the published address (the file outlives a crash)."""
    import socket

    try:
        port = int(json.loads(bridge_file(data_dir).read_text("utf-8"))["port"])
        with socket.create_connection(("127.0.0.1", port), timeout=1):
            return True
    except (OSError, ValueError, KeyError):
        return False


def withdraw_address(data_dir: Path) -> None:
    path = bridge_file(data_dir)
    with contextlib.suppress(OSError, ValueError):
        if json.loads(path.read_text("utf-8")).get("pid") == os.getpid():
            path.unlink()
