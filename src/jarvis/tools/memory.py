"""Memory: facts you ask Jarvis to remember ("remember that my manager is Ravi").

Memories are private. They are added to the local model's system prompt as facts you stated,
never as instructions, and a cloud turn never sees them (ADR-045). Because they come back in
every later prompt, saving one while outside content (a web page, a message, a file) is in the
conversation asks first: otherwise a page could plant a lasting instruction (ADR-046).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from operator import attrgetter
from typing import Any

from jarvis.storage.db import Database
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.naming import pick
from jarvis.tools.registry import tool

MAX_MEMORIES = 100
MAX_CHARS = 300
PROMPT_MEMORIES = 30  # newest first, so the prompt stays small for an 8B model
_LEAD = re.compile(r"^\s*(remember|note|keep in mind)( that)?[:,]?\s+", re.IGNORECASE)


@dataclass(frozen=True)
class Memory:
    id: int
    text: str
    created: datetime


class MemoryStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def all(self) -> list[Memory]:
        rows = self._db.execute("SELECT id, text, created_at FROM memories ORDER BY id DESC")
        return [Memory(r["id"], r["text"], datetime.fromisoformat(r["created_at"])) for r in rows]

    def texts(self) -> list[str]:
        return [memory.text for memory in self.all()[:PROMPT_MEMORIES]]

    def add(self, text: str) -> Memory:
        rows = self._db.execute(
            "INSERT INTO memories (text, created_at) VALUES (?, ?) RETURNING id",
            (text, datetime.now(UTC).isoformat()),
        )
        return Memory(int(rows[0][0]), text, datetime.now(UTC))

    def remove(self, ids: list[int]) -> None:
        self._db.executemany("DELETE FROM memories WHERE id = ?", [(i,) for i in ids])


def clean(fact: str) -> str:
    return " ".join(_LEAD.sub("", fact).split()).rstrip(".")


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def remember(ctx: ToolContext, fact: str) -> ToolResult:
    """Remember a fact the user tells you to keep, for example "remember that my manager is
    Ravi". Write it as a short statement about the user.

    Args:
        fact: The fact as one short sentence, for example "The user's manager is Ravi".
    """
    store = ctx.services.memory
    memory = store.add(fact)
    return ToolResult.success(
        data={"remembered": memory.text}, speech="Got it, I'll remember that."
    )


@remember.preparer
async def _prepare_remember(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    fact = clean(str(args["fact"]))
    if not fact:
        raise ToolError("There is nothing to remember. Ask the user what to keep.")
    if len(fact) > MAX_CHARS:
        raise ToolError(f"That is longer than {MAX_CHARS} characters; keep it to one sentence.")
    store = ctx.services.memory
    if len(store.all()) >= MAX_MEMORIES:
        raise ToolError(f"I already keep {MAX_MEMORIES} memories. Ask the user what to forget.")
    if any(memory.text.casefold() == fact.casefold() for memory in store.all()):
        raise ToolError("I already remember exactly that.")
    risk, reason = Risk.SAFE, None
    if ctx.flags.untrusted:
        risk = Risk.CONFIRM
        reason = "outside content is in this conversation, and a memory comes back in every prompt"
    return Prepared(args={"fact": fact}, summary=f'Remember: "{fact}"', risk=risk, reason=reason)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def list_memories(ctx: ToolContext) -> ToolResult:
    """Say what you remember about the user ("what do you remember about me")."""
    memories = ctx.services.memory.all()
    if not memories:
        return ToolResult.success(data={"count": 0}, speech="I don't have anything remembered yet.")
    return ToolResult.success(
        data={"count": len(memories), "memories": [m.text for m in memories]},
        speech="I remember: " + ". ".join(m.text for m in memories[:5]) + ".",
    )


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=5)
async def forget(ctx: ToolContext, what: str) -> ToolResult:
    """Forget something you were asked to remember ("forget that my manager is Ravi").

    Args:
        what: Words from the memory to forget, for example "my manager", or "everything".
    """
    match = re.fullmatch(r"id:([\d,]+)", what)
    if match is None:
        raise ToolError("Nothing was confirmed to forget.")
    ids = [int(i) for i in match.group(1).split(",")]
    ctx.services.memory.remove(ids)
    count = "that" if len(ids) == 1 else f"those {len(ids)} things"
    return ToolResult.success(data={"forgotten": len(ids)}, speech=f"Okay, I've forgotten {count}.")


@forget.preparer
async def _prepare_forget(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    memories = ctx.services.memory.all()
    if not memories:
        raise ToolError("There is nothing remembered to forget.")
    what = str(args["what"]).strip()
    if what.casefold() in {"everything", "all", "all of it", "everything you remember"}:
        chosen = memories
    else:
        best, rival = pick(what, memories, attrgetter("text"), score=60)
        if best is None:
            raise ToolError(f"I don't remember anything about '{what}'.")
        if rival is not None:
            raise ToolError(
                f'\'{what}\' could be "{best.text}" or "{rival.text}". Ask the user which.'
            )
        chosen = [best]
    texts = "; ".join(f'"{m.text}"' for m in chosen[:3])
    more = f" and {len(chosen) - 3} more" if len(chosen) > 3 else ""
    return Prepared(
        args={"what": "id:" + ",".join(str(m.id) for m in chosen)},
        summary=f"Forget {texts}{more}",
        risk=Risk.CONFIRM,
        reason="forgetting deletes it",
    )
