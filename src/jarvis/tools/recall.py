"""Recall: memories and past commands found by meaning (ADR-065).

"What did I ask about Docker last week" searches the local command history (what you said and
what Jarvis answered) by meaning, within a time range. Memories relevant to a request are
found the same way and repeated next to it for the model, so hundreds of memories work, not
only the newest few. Without the embedding model both fall back to shared words.

The results are private, and untrusted: an old answer may quote a web page or a message.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from jarvis.core.meaning import MeaningUnavailable
from jarvis.core.prompts import related_memories
from jarvis.services import Services
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

MEMORY_MATCH = 0.51  # measured: unrelated requests scored up to 0.49, real matches 0.52 to 0.77
MEMORY_MARGIN = 0.06
HISTORY_MATCH = 0.5
ANSWER_CHARS = 200
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]


async def relevant_memories(services: Services, request: str, limit: int = 3) -> list[str]:
    """Memories that fit the request, by meaning when possible, else by shared words."""
    memories = services.memory.all()
    index = services.meaning
    if index is not None:
        try:
            # Even with none left: forgetting the last memory must drop its vector too.
            await index.sync("memory", [(m.id, m.text) for m in memories])
            if not memories:
                return []
            found = await index.search("memory", request, limit=limit)
        except MeaningUnavailable as exc:
            log.info("Memory search by meaning unavailable (%s); using words", exc)
        else:
            texts = {m.id: m.text for m in memories}
            best = found[0][1] if found else 0.0
            return [
                texts[i]
                for i, score in found
                if score >= MEMORY_MATCH and best - score <= MEMORY_MARGIN and i in texts
            ]
    return related_memories(request, [m.text for m in memories])[:limit]


def past_range(when: str, now: datetime) -> tuple[datetime, datetime, str]:
    """(start, end, label) for today, yesterday, this week, last week, this month, last
    month, a weekday (the last one), a date, "N days ago", or anything else as all time."""
    words = " ".join(when.casefold().split()).removeprefix("on ").removeprefix("last ")
    raw = " ".join(when.casefold().split())
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    if raw in ("", "ever", "all", "any time", "anytime", "all time"):
        return datetime.min.replace(tzinfo=now.tzinfo), now, "ever"
    if raw == "today":
        return midnight, now, "today"
    if raw == "yesterday":
        return midnight - timedelta(days=1), midnight, "yesterday"
    week_start = midnight - timedelta(days=midnight.weekday())
    if raw == "this week":
        return week_start, now, "this week"
    if raw in ("last week", "past week"):
        return week_start - timedelta(days=7), week_start, "last week"
    month_start = midnight.replace(day=1)
    if raw == "this month":
        return month_start, now, "this month"
    if raw in ("last month", "past month"):
        previous = (month_start - timedelta(days=1)).replace(day=1)
        return previous, month_start, "last month"
    if words in WEEKDAYS:
        back = (midnight.weekday() - WEEKDAYS.index(words)) % 7 or 7
        start = midnight - timedelta(days=back)
        return start, start + timedelta(days=1), f"on {words.capitalize()}"
    parts = raw.split()
    if len(parts) == 3 and parts[1] in ("days", "day") and parts[2] == "ago" and parts[0].isdigit():
        start = midnight - timedelta(days=int(parts[0]))
        return start, start + timedelta(days=1), raw
    try:
        day = datetime.fromisoformat(raw).replace(tzinfo=now.tzinfo)
    except ValueError:
        return datetime.min.replace(tzinfo=now.tzinfo), now, "ever"
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    return start, start + timedelta(days=1), f"on {start.strftime('%A %d %B')}"


def _spoken_when(moment: datetime, now: datetime) -> str:
    local = moment.astimezone()
    clock = local.strftime("%I:%M %p").lstrip("0")
    if local.date() == now.date():
        return f"today at {clock}"
    if local.date() == (now - timedelta(days=1)).date():
        return f"yesterday at {clock}"
    if (now - local).days < 7:
        return f"{local.strftime('%A')} at {clock}"
    return local.strftime("%d %B")


def _words_match(query: str, text: str) -> bool:
    asked = set(query.casefold().split()) - {"i", "the", "a", "about", "what", "did", "my", "me"}
    return bool(asked & set(text.casefold().split()))


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=60)
async def recall(ctx: ToolContext, about: str, when: str | None = None) -> ToolResult:
    """Look back at what the user asked Jarvis before and what Jarvis answered, for "what did I
    ask about Docker last week", "when did I message Ravi", or "what was that song I asked
    about yesterday".

    Args:
        about: What the earlier request was about, in a few words, for example "docker".
        when: today, yesterday, this week, last week, this month, last month, a weekday, a
            date as YYYY-MM-DD, or leave it out for any time.
    """
    now = datetime.now().astimezone()
    start, end, label = past_range(when or "", now)
    history = ctx.services.history
    rows = history.between(start, end, exclude_turn=ctx.turn_id) if history else []
    if not rows:
        return ToolResult.success(data={"found": []}, speech=f"I have no commands from {label}.")
    found: list[dict[str, Any]] = []
    index = ctx.services.meaning
    by_id = {row["id"]: row for row in rows}
    picked: list[int] = []
    if index is not None:
        try:
            await index.sync("history", [(row["id"], row["input_text"]) for row in rows])
            hits = await index.search("history", about, among=list(by_id), limit=5)
            picked = [i for i, score in hits if score >= HISTORY_MATCH]
        except MeaningUnavailable as exc:
            log.info("History search by meaning unavailable (%s); using words", exc)
            index = None
    if index is None:
        picked = [row["id"] for row in rows if _words_match(about, row["input_text"])][-5:][::-1]
    for item_id in picked:
        row = by_id[item_id]
        answer = " ".join(str(row["response_text"] or "").split())
        if len(answer) > ANSWER_CHARS:
            answer = answer[: ANSWER_CHARS - 3] + "..."
        found.append(
            {
                "when": _spoken_when(datetime.fromisoformat(row["ts"]), now),
                "you_said": row["input_text"],
                "jarvis_answered": answer,
            }
        )
    if not found:
        raise ToolError(f"I found nothing about {about} from {label}.")
    first = found[0]
    speech = f'{first["when"].capitalize()} you asked "{first["you_said"]}".'
    if len(found) > 1:
        speech += f" And {len(found) - 1} more like it."
    return ToolResult.success(data={"range": label, "found": found}, speech=speech)
