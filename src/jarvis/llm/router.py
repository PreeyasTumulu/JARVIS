"""Which model answers a turn: the local model, or a free cloud model for a heavy public question.

Rules (ARCHITECTURE.md 7.2, ADR-045):

- The local model is the default and answers anything that touches private data: files,
  messages, notifications, the clipboard, the screen, memory, or apps on this laptop.
- A turn may go to the cloud when you ask for it ("think harder", "use the cloud model") or, in
  `escalate = "auto"`, when it reads like a reasoning question and is only about public topics.
- Cloud providers are tried in order (Groq, then OpenRouter), each skipped when its key is
  missing, its daily request cap is used up, or it failed in the last few minutes. If none can
  answer, the local model does.

The privacy guard is code: a cloud turn starts from a fresh context (the system prompt and the
request, never earlier history or memories), sees only public read-only tools, and
`CloudModel.complete` raises if anything private or any other tool is about to be sent.
"""

from __future__ import annotations

import logging
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from jarvis.config import ConfigError, Settings
from jarvis.core.tool_routing import matched_groups
from jarvis.llm.types import ChatModel, LLMReply
from jarvis.storage.db import Database

log = logging.getLogger(__name__)

# Tools a cloud turn may use: public data, read only, no side effects on this laptop.
CLOUD_TOOLS = (
    "web_search",
    "fetch_page",
    "market_data",
    "crypto_price",
    "convert_currency",
    "weather",
)
# Requests about these topics only reach public tools. Anything else stays local.
PUBLIC_GROUPS = {"web", "questions", "market", "weather"}
EXPLICIT = re.compile(
    r"\b(think (it through|harder|hard|deeply|carefully)|use (the|your) (cloud|big|bigger|"
    r"smart|smarter) model|ask the (cloud|big model|bigger model)|reason (it out|carefully)|"
    r"step by step|in depth)\b"
)
HEAVY = re.compile(
    r"\b(why|explain|compare|comparison|difference between|pros and cons|trade ?offs?|plan|"
    r"strategy|analy[sz]e|analysis|design|derive|prove|calculate|estimate|solve|evaluate|"
    r"recommend|should i|what would happen|how does|how do|how would|walk me through)\b"
)
MIN_WORDS = 8


class PrivacyViolation(Exception):
    """Private content or a private tool was about to reach a cloud model. This is a bug."""


@dataclass
class CloudModel:
    """A cloud model behind the privacy guard."""

    name: str
    client: ChatModel

    @property
    def model(self) -> str:
        return self.client.model

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], *, private: bool
    ) -> LLMReply:
        if private:
            raise PrivacyViolation(f"Refusing to send private content to {self.name}.")
        names = {tool["function"]["name"] for tool in tools}
        if not names <= set(CLOUD_TOOLS):
            raise PrivacyViolation(
                f"Refusing to offer {sorted(names - set(CLOUD_TOOLS))} to the cloud."
            )
        return await self.client.complete(messages, tools)


def wants_cloud(text: str, escalate: str) -> bool:
    """Whether a request may go to the cloud at all (the privacy part of the decision)."""
    if escalate == "never":
        return False
    lowered = text.casefold()
    groups = set(matched_groups(lowered))
    if groups and not groups <= PUBLIC_GROUPS:
        return False  # it touches apps, files, messages, the screen, memory, ...
    if EXPLICIT.search(lowered):
        return True
    if escalate != "auto":
        return False
    return len(lowered.split()) >= MIN_WORDS and bool(HEAVY.search(lowered))


class CloudUsage:
    """Requests and tokens per provider per day, so free daily limits are respected."""

    def __init__(self, db: Database, clock: Callable[[], datetime]) -> None:
        self._db = db
        self._clock = clock

    def _day(self) -> str:
        return self._clock().date().isoformat()

    def today(self, provider: str) -> int:
        rows = self._db.execute(
            "SELECT requests FROM cloud_usage WHERE day = ? AND provider = ?",
            (self._day(), provider),
        )
        return int(rows[0][0]) if rows else 0

    def count(self, provider: str, reply: LLMReply) -> None:
        self._db.execute(
            """
            INSERT INTO cloud_usage (day, provider, requests, prompt_tokens, completion_tokens)
            VALUES (?, ?, 1, ?, ?)
            ON CONFLICT (day, provider) DO UPDATE SET
                requests = requests + 1,
                prompt_tokens = prompt_tokens + excluded.prompt_tokens,
                completion_tokens = completion_tokens + excluded.completion_tokens
            """,
            (self._day(), provider, reply.prompt_tokens, reply.completion_tokens),
        )


class Router:
    def __init__(
        self,
        settings: Settings,
        db: Database,
        *,
        clients: dict[str, ChatModel] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._clients: dict[str, ChatModel] = dict(clients or {})
        self._unusable: set[str] = set()
        self._cooling: dict[str, float] = {}
        self.usage = CloudUsage(db, clock or (lambda: datetime.now(UTC)))

    def wants_cloud(self, text: str) -> bool:
        return bool(self._settings.router.cloud) and wants_cloud(
            text, self._settings.router.escalate
        )

    def available(self) -> list[CloudModel]:
        """Cloud models that may answer right now, in the configured order."""
        router = self._settings.router
        ready: list[CloudModel] = []
        for name in router.cloud:
            if name in self._unusable or self._cooling.get(name, 0) > time.monotonic():
                continue
            cap = router.daily_requests.get(name)
            if cap is not None and self.usage.today(name) >= cap:
                continue
            client = self._client(name)
            if client is not None:
                ready.append(CloudModel(name, client))
        return ready

    def succeeded(self, model: CloudModel, reply: LLMReply) -> None:
        self.usage.count(model.name, reply)

    def failed(self, model: CloudModel, reason: str) -> None:
        log.info("Cloud model %s is skipped for a while: %s", model.name, reason)
        self._cooling[model.name] = time.monotonic() + self._settings.router.cooldown_s

    def _client(self, name: str) -> ChatModel | None:
        if name in self._clients:
            return self._clients[name]
        provider = self._settings.llm.providers.get(name)
        if provider is None:
            log.warning(
                "[router] cloud lists %r, but [llm.providers.%s] does not exist", name, name
            )
            self._unusable.add(name)
            return None
        from jarvis.llm.client import LLMClient

        try:
            client = LLMClient(provider)
        except ConfigError:
            log.info("No API key for %s in .env, so it is not used", name)
            self._unusable.add(name)
            return None
        self._clients[name] = client
        return client

    async def aclose(self) -> None:
        for client in self._clients.values():
            await client.aclose()
