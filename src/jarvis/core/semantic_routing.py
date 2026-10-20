"""Tool groups by meaning, when no keyword matched (ADR-063).

Keyword routing (core/tool_routing.py) misses paraphrases: "what do I have going on tomorrow"
names no calendar word, so the model got every tool and often picked web search. Here each
group has a few example requests that avoid its keywords; they and the request are embedded
with nomic-embed-text through Ollama, and the groups whose closest example is similar enough
are offered. Keywords still decide whenever they match; this only replaces "every tool".

The example vectors are computed once and cached in the data folder. Any failure (Ollama
down, the model missing, too slow) just means no help: routing falls back as before.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
from pathlib import Path
from typing import Any

import httpx
import numpy as np

from jarvis.config import AgentSettings

log = logging.getLogger(__name__)

# nomic-embed-text wants a task prefix on every text.
QUERY = "search_query: "
DOCUMENT = "search_query: "  # the examples are requests too, so both sides use the query prefix

# Requests that mean a group without saying its keywords.
EXAMPLES: dict[str, tuple[str, ...]] = {
    "apps": ("fire up the calculator", "get me into spotify", "kill chrome"),
    "files": ("where did I put my cv", "show me the thing I downloaded yesterday"),
    "docker": ("is the database container up", "restart my local postgres box"),
    "market": (
        "how is reliance doing today",
        "what's tesla trading at",
        "how much is one usd in inr",
        "what's tcs at right now",
        "where is the nifty",
    ),
    "weather": (
        "do I need a jacket today",
        "will it be sunny tomorrow in delhi",
        "how hot is it outside",
    ),
    "system": ("I can't hear anything, turn it up", "it's too bright", "make it quieter"),
    "time": ("ping me in twenty minutes", "wake me at six", "nudge me to drink water later"),
    "messaging": ("let mom know I'm on my way", "text ravi I'll be late", "drop a line to dad"),
    "calls": ("ring my sister", "get dad on the line"),
    "notifications": ("did anybody write to me", "anything I missed while I was away"),
    "media": (
        "I'm done with this song",
        "hold the track",
        "go back to the last song",
        "put on some tunes",
        "I want to hear something",
    ),
    "mail": (
        "did my manager write back",
        "anything new in my inbox from the bank",
        "answer ravi's message saying yes",
    ),
    "calendar": (
        "what do I have going on tomorrow",
        "when is my next call",
        "am I booked on friday afternoon",
    ),
    "memory": (
        "what was that thing I asked you before",
        "remind me what we talked about this morning",
        "keep in mind that my car is a swift",
        "what do you know about my family",
    ),
    "ui": ("put hello in the text box", "hit save in paint"),
}


def _cosine(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(vector)
    result: np.ndarray = matrix @ vector / np.where(norms == 0, 1, norms)
    return result


class SemanticRouter:
    def __init__(
        self,
        settings: AgentSettings,
        base_url: str,
        cache_dir: Path,
        http: httpx.AsyncClient | None = None,
        examples: dict[str, tuple[str, ...]] | None = None,
    ) -> None:
        self._cfg = settings
        self._url = base_url.rstrip("/") + "/embeddings"
        self._cache = cache_dir / "route-embeddings.json"
        self._http = http
        self._examples = examples or EXAMPLES
        self._labels: list[str] = []
        self._matrix: np.ndarray | None = None
        self._lock = asyncio.Lock()
        self._broken = False

    @property
    def enabled(self) -> bool:
        return self._cfg.semantic_routing and not self._broken

    async def _embed(self, texts: list[str]) -> np.ndarray:
        http = self._http or httpx.AsyncClient()
        try:
            response = await http.post(
                self._url,
                json={"model": self._cfg.semantic_model, "input": texts},
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()["data"]
        finally:
            if self._http is None:
                await http.aclose()
        return np.array([item["embedding"] for item in data], dtype=np.float32)

    def _key(self) -> str:
        flat = json.dumps([self._cfg.semantic_model, self._examples], sort_keys=True)
        return hashlib.sha256(flat.encode()).hexdigest()[:16]

    async def _index(self) -> tuple[list[str], np.ndarray]:
        async with self._lock:
            if self._matrix is not None:
                return self._labels, self._matrix
            labels = [group for group, texts in self._examples.items() for _ in texts]
            texts = [DOCUMENT + text for group in self._examples for text in self._examples[group]]
            key = self._key()
            matrix: np.ndarray | None = None
            try:
                cached: dict[str, Any] = json.loads(self._cache.read_text(encoding="utf-8"))
                if cached.get("key") == key:
                    matrix = np.array(cached["vectors"], dtype=np.float32)
            except (OSError, ValueError, KeyError):
                pass
            if matrix is None:
                matrix = await self._embed(texts)
                try:
                    self._cache.parent.mkdir(parents=True, exist_ok=True)
                    payload = {"key": key, "vectors": matrix.round(5).tolist()}
                    self._cache.write_text(json.dumps(payload), encoding="utf-8")
                except OSError:
                    log.debug("Could not cache the routing embeddings", exc_info=True)
            self._labels, self._matrix = labels, matrix
            return labels, matrix

    async def warm(self) -> None:
        """Load the embedding model and the examples ahead of the first request (serve)."""
        if self.enabled:
            try:
                await self.scores("hello")
            except Exception as exc:
                log.info("Semantic routing is off (%s)", exc)
                self._broken = True

    async def scores(self, text: str) -> dict[str, float]:
        """Each group's best similarity to the request."""
        labels, matrix = await self._index()
        query = (await self._embed([QUERY + text]))[0]
        similarity = _cosine(matrix, query)
        best: dict[str, float] = {}
        for label, value in zip(labels, similarity.tolist(), strict=True):
            best[label] = max(best.get(label, -1.0), float(value))
        return best

    async def groups(self, text: str) -> list[str]:
        """The groups meant, best first: at most two, each above the threshold and close to the
        best one. Empty when unsure or when anything fails."""
        if not self.enabled:
            return []
        try:
            async with asyncio.timeout(self._cfg.semantic_timeout_s):
                best = await self.scores(text)
        except TimeoutError:
            log.info(
                "Semantic routing took longer than %.1fs; skipped", self._cfg.semantic_timeout_s
            )
            return []
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            log.warning("Semantic routing is off for this run (%s)", exc)
            self._broken = True
            return []
        ranked = sorted(best.items(), key=lambda item: item[1], reverse=True)
        if not ranked or ranked[0][1] < self._cfg.semantic_threshold:
            return []
        top = ranked[0][1]
        return [g for g, s in ranked[:2] if s >= self._cfg.semantic_threshold and top - s <= 0.03]
