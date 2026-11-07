"""The router pipeline: ordered stages that may handle a request before any model sees it.

Taken from OpenVoiceOS's intent pipeline and Home Assistant's "prefer handling commands
locally" (docs/RESEARCH.md section 6.2, ADR-083). Each stage answers "this tool call" or "not
mine" within a time limit, and the first match wins. The last stage, "agent", is the model.
A match is only a proposed call: it enters the agent graph at the guard node and passes the
policy gate like any call the model makes, so a stage can never run a tool by itself.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass

from jarvis.core.fast_path import exact_call
from jarvis.services import Services
from jarvis.tools.registry import Registry
from jarvis.tools.system.arithmetic import spoken_math
from jarvis.voice.phrases import normalize, parse_yes, strip_wake_word

log = logging.getLogger(__name__)

AGENT = "agent"
CLOUD = "cloud"  # recorded as handled_by when a cloud model answered the agent stage
FAST_STAGES = ("exact_phrase", "arithmetic", "template")


@dataclass(frozen=True)
class RouteRequest:
    text: str
    registry: Registry
    services: Services
    offer_pending: bool = False  # the last reply offered the morning briefing


@dataclass(frozen=True)
class Routed:
    """A stage's answer: run this tool with these JSON arguments, without the model."""

    stage: str
    name: str
    arguments: str


StageFn = Callable[[RouteRequest], Awaitable[tuple[str, str] | None]]


async def exact_phrase(request: RouteRequest) -> tuple[str, str] | None:
    """Whole short commands ("pause the music", "hang up") and "yes" to the briefing offer."""
    if request.offer_pending and parse_yes(request.text):
        return "briefing", "{}"
    return exact_call(request.text)


async def arithmetic(request: RouteRequest) -> tuple[str, str] | None:
    """A request that is only a sum (ADR-082)."""
    expression = spoken_math(request.text)  # the raw text: normalizing would drop + and *
    if expression is None:
        return None
    return "calculate", json.dumps({"expression": expression})


_OPEN = re.compile(r"^(?:open|launch|start|run)\s+(?:the\s+)?(?P<app>[\w .+#-]{2,40}?)(?:\s+app)?$")
_VOLUME = re.compile(
    r"^(?:set\s+)?(?:the\s+)?volume\s+(?:to\s+|at\s+)?(?P<level>\d{1,3})\s*(?:percent|%)?$"
)
_MUTE = {"mute": True, "mute the volume": True, "unmute": False, "unmute the volume": False}
# "note that the plumber comes on tuesday", "jot down buy milk", "make a note: call the bank".
# The live test saw the model call take_note with read_notes' argument instead.
# "Add a note to call mom" is left to the model: "add a note to ..." can mean a calendar event
# or another app's notes (an MCP notes server, in a test), so those words need "that" or ":".
_NOTE = re.compile(
    r"^(?:please\s+)?(?:(?:note|jot)(?:\s+down)?(?:\s+that)?|write\s+down(?:\s+that)?|"
    r"(?:make|take|add)\s+a\s+note\s*(?:that|:))\s*:?\s+(?P<text>\S.{1,1999})$",
    re.I | re.S,
)


def _words(text: str) -> str:
    phrase = normalize(strip_wake_word(text)).removeprefix("please ").removesuffix(" please")
    return phrase.removesuffix(" jarvis").removesuffix(" now")


async def template(request: RouteRequest) -> tuple[str, str] | None:
    """Commands with one slot, filled from what is on this laptop ("open {app}", "volume {n}").

    "open {app}" matches only when the app is an exact name or alias in the app index, so
    "open my report" still goes to the model, which knows files and sites ("open youtube"
    opens the YouTube app only when one is installed). On a fresh data folder the first scan
    of the Start menu outlives the stage's time limit, and that one request goes to the model.
    """
    # "note that ..." keeps the user's own words, case and punctuation, so it reads the raw text.
    note = _NOTE.match(strip_wake_word(request.text).strip())
    if note is not None:
        return "take_note", json.dumps({"text": note["text"].strip()}, ensure_ascii=False)
    phrase = _words(request.text)
    volume = _VOLUME.match(phrase)
    if volume is not None:
        level = int(volume["level"])
        return ("set_volume", json.dumps({"level": level})) if level <= 100 else None
    if phrase in _MUTE:
        return "set_volume", json.dumps({"mute": _MUTE[phrase]})
    opened = _OPEN.match(phrase)
    if opened is not None:
        apps = request.services.apps
        spoken = opened["app"].strip()
        # Shielded: a first scan of the Start menu outlives the stage's time limit, and
        # cancelling it would only make the next request scan again.
        entries = await asyncio.shield(apps.entries())
        entry = entries.get(normalize(apps.canonical(spoken)))
        if entry is not None:
            return "open_app", json.dumps({"name": entry.name})
    return None


STAGES: dict[str, StageFn] = {
    "exact_phrase": exact_phrase,
    "arithmetic": arithmetic,
    "template": template,
}


async def route(
    request: RouteRequest, pipeline: Sequence[str], timeout_ms: int
) -> tuple[Routed | None, dict[str, int]]:
    """The first stage that handles the request, and how long each stage took (ms)."""
    timings: dict[str, int] = {}
    for stage in pipeline:
        if stage == AGENT:
            break
        started = time.perf_counter()
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                found = await STAGES[stage](request)
        except TimeoutError:
            log.info("Router stage %s took longer than %d ms; skipped", stage, timeout_ms)
            found = None
        except Exception:
            log.exception("Router stage %s failed; skipped", stage)
            found = None
        timings[stage] = int((time.perf_counter() - started) * 1000)
        if found is not None and request.registry.get(found[0]) is not None:
            return Routed(stage, *found), timings
    return None, timings
