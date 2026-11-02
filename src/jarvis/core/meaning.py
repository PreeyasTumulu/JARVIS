"""Search by meaning: embeddings from nomic-embed-text through Ollama, kept in SQLite (ADR-065).

Memories and past commands are embedded once and stored in the `embeddings` table, so a
search embeds only the question. Everything stays on this laptop. When Ollama or the model is
missing, `MeaningIndex` raises `MeaningUnavailable` and callers fall back to matching words.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Sequence

import httpx
import numpy as np

from jarvis.storage.db import Database

log = logging.getLogger(__name__)

QUERY = "search_query: "  # nomic-embed-text wants a task prefix on every text
DOCUMENT = "search_document: "
BATCH = 64


class MeaningUnavailable(Exception):
    """The embedding model could not be reached; search by words instead."""


class Embedder:
    def __init__(self, base_url: str, model: str, http: httpx.AsyncClient | None = None) -> None:
        self._url = base_url.rstrip("/") + "/embeddings"
        self.model = model
        self._http = http

    async def embed(self, texts: Sequence[str]) -> np.ndarray:
        http = self._http or httpx.AsyncClient()
        try:
            response = await http.post(
                self._url, json={"model": self.model, "input": list(texts)}, timeout=60
            )
            response.raise_for_status()
            data = response.json()["data"]
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            raise MeaningUnavailable(str(exc)) from exc
        finally:
            if self._http is None:
                await http.aclose()
        return np.array([item["embedding"] for item in data], dtype=np.float32)


def cosine(matrix: np.ndarray, vector: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(matrix, axis=1) * np.linalg.norm(vector)
    result: np.ndarray = matrix @ vector / np.where(norms == 0, 1, norms)
    return result


class MeaningIndex:
    """Vectors per (kind, id): "memory" rows and "history" rows, computed on demand."""

    def __init__(self, db: Database, embedder: Embedder) -> None:
        self._db = db
        self._embedder = embedder
        self._lock = asyncio.Lock()

    async def sync(self, kind: str, items: Sequence[tuple[int, str]]) -> None:
        """Embed the items that have no vector yet (in batches); drop vectors of deleted ones."""
        async with self._lock:
            model = self._embedder.model
            have = {
                int(row["ref_id"])
                for row in self._db.execute(
                    "SELECT ref_id FROM embeddings WHERE kind = ? AND model = ?", (kind, model)
                )
            }
            wanted = {item_id for item_id, _ in items}
            stale = have - wanted
            if stale:
                self._db.executemany(
                    "DELETE FROM embeddings WHERE kind = ? AND ref_id = ?",
                    [(kind, i) for i in stale],
                )
            missing = [(i, text) for i, text in items if i not in have]
            for start in range(0, len(missing), BATCH):
                chunk = missing[start : start + BATCH]
                vectors = await self._embedder.embed([DOCUMENT + text for _, text in chunk])
                self._db.executemany(
                    "INSERT OR REPLACE INTO embeddings (kind, ref_id, model, vector) "
                    "VALUES (?, ?, ?, ?)",
                    [
                        (kind, i, model, vector.astype(np.float32).tobytes())
                        for (i, _), vector in zip(chunk, vectors, strict=True)
                    ],
                )

    async def search(
        self, kind: str, query: str, among: Sequence[int] | None = None, limit: int = 5
    ) -> list[tuple[int, float]]:
        """(id, similarity) best first, optionally only among some ids."""
        rows = self._db.execute(
            "SELECT ref_id, vector FROM embeddings WHERE kind = ? AND model = ?",
            (kind, self._embedder.model),
        )
        allowed = set(among) if among is not None else None
        ids, vectors = [], []
        for row in rows:
            if allowed is None or int(row["ref_id"]) in allowed:
                ids.append(int(row["ref_id"]))
                vectors.append(np.frombuffer(row["vector"], dtype=np.float32))
        if not ids:
            return []
        query_vector = (await self._embedder.embed([QUERY + query]))[0]
        scores = cosine(np.vstack(vectors), query_vector)
        order = np.argsort(-scores)[:limit]
        return [(ids[i], float(scores[i])) for i in order]
