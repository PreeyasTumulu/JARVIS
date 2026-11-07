"""Search by meaning: embeddings from nomic-embed-text through Ollama, kept in ChromaDB.

Memories and past commands are embedded once and stored in a ChromaDB folder inside the data
folder (ADR-079), so a search embeds only the question. Jarvis hands ChromaDB the vectors
itself: ChromaDB never loads or downloads an embedding model of its own, its telemetry is off,
and nothing leaves the laptop. The text stays in SQLite; ChromaDB holds ids and vectors.

On the first start the vectors already in SQLite (Phase 14) are copied over as they are, so no
re-embedding is needed. If ChromaDB cannot open, the SQLite table is used as before; it is
kept for one release as that fallback (ADR-084). When Ollama or the model is missing, every
method raises `MeaningUnavailable` and callers fall back to matching words.
"""

from __future__ import annotations

import asyncio
import logging
import re
import threading
from collections.abc import Sequence
from pathlib import Path
from typing import Any, Protocol

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


class VectorStore(Protocol):
    """Where vectors live: ChromaDB, or the SQLite table it replaced."""

    def ids(self, kind: str, model: str) -> set[int]: ...

    def count(self, kind: str, model: str) -> int: ...

    def put(self, kind: str, model: str, items: Sequence[tuple[int, np.ndarray]]) -> None: ...

    def delete(self, kind: str, model: str, ids: Sequence[int]) -> None: ...

    def nearest(
        self,
        kind: str,
        model: str,
        vector: np.ndarray,
        among: Sequence[int] | None,
        limit: int,
    ) -> list[tuple[int, float]]: ...


class SqliteVectors:
    """The Phase 14 store: one BLOB per vector, searched by a full scan."""

    def __init__(self, db: Database) -> None:
        self._db = db

    def ids(self, kind: str, model: str) -> set[int]:
        rows = self._db.execute(
            "SELECT ref_id FROM embeddings WHERE kind = ? AND model = ?", (kind, model)
        )
        return {int(row["ref_id"]) for row in rows}

    def count(self, kind: str, model: str) -> int:
        rows = self._db.execute(
            "SELECT COUNT(*) FROM embeddings WHERE kind = ? AND model = ?", (kind, model)
        )
        return int(rows[0][0])

    def put(self, kind: str, model: str, items: Sequence[tuple[int, np.ndarray]]) -> None:
        self._db.executemany(
            "INSERT OR REPLACE INTO embeddings (kind, ref_id, model, vector) VALUES (?, ?, ?, ?)",
            [(kind, i, model, v.astype(np.float32).tobytes()) for i, v in items],
        )

    def delete(self, kind: str, model: str, ids: Sequence[int]) -> None:
        self._db.executemany(
            "DELETE FROM embeddings WHERE kind = ? AND ref_id = ? AND model = ?",
            [(kind, i, model) for i in ids],
        )

    def all(self, kind: str, model: str) -> list[tuple[int, np.ndarray]]:
        rows = self._db.execute(
            "SELECT ref_id, vector FROM embeddings WHERE kind = ? AND model = ?", (kind, model)
        )
        return [(int(r["ref_id"]), np.frombuffer(r["vector"], dtype=np.float32)) for r in rows]

    def nearest(
        self,
        kind: str,
        model: str,
        vector: np.ndarray,
        among: Sequence[int] | None,
        limit: int,
    ) -> list[tuple[int, float]]:
        allowed = set(among) if among is not None else None
        stored = [(i, v) for i, v in self.all(kind, model) if allowed is None or i in allowed]
        if not stored:
            return []
        scores = cosine(np.vstack([v for _, v in stored]), vector)
        order = np.argsort(-scores)[:limit]
        return [(stored[i][0], float(scores[i])) for i in order]


class ChromaVectors:
    """A ChromaDB persistent store, one collection per kind and embedding model."""

    def __init__(self, path: Path, legacy: SqliteVectors | None = None) -> None:
        import chromadb
        from chromadb.config import Settings as ChromaSettings

        path.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(
            path=str(path),
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=False),
        )
        self._legacy = legacy
        self._collections: dict[tuple[str, str], Any] = {}

    def _collection(self, kind: str, model: str) -> Any:
        key = (kind, model)
        if key not in self._collections:
            name = re.sub(r"[^A-Za-z0-9._-]", "-", f"{kind}__{model}")[:60]
            collection = self._client.get_or_create_collection(
                name, embedding_function=None, metadata={"hnsw:space": "cosine"}
            )
            self._collections[key] = collection
            if collection.count() == 0 and self._legacy is not None:
                copied = self._legacy.all(kind, model)
                if copied:
                    self._put(collection, copied)
                    log.info("Copied %d %s vectors from SQLite to ChromaDB", len(copied), kind)
        return self._collections[key]

    def ids(self, kind: str, model: str) -> set[int]:
        found = self._collection(kind, model).get(include=[])
        return {int(i) for i in found["ids"]}

    def count(self, kind: str, model: str) -> int:
        return int(self._collection(kind, model).count())

    def put(self, kind: str, model: str, items: Sequence[tuple[int, np.ndarray]]) -> None:
        if items:
            self._put(self._collection(kind, model), items)

    def delete(self, kind: str, model: str, ids: Sequence[int]) -> None:
        if ids:
            self._collection(kind, model).delete(ids=[str(i) for i in ids])

    def nearest(
        self,
        kind: str,
        model: str,
        vector: np.ndarray,
        among: Sequence[int] | None,
        limit: int,
    ) -> list[tuple[int, float]]:
        collection = self._collection(kind, model)
        count = collection.count()
        if count == 0 or (among is not None and not among):
            return []
        where = {"ref_id": {"$in": [int(i) for i in among]}} if among is not None else None
        found = collection.query(
            query_embeddings=[vector.astype(np.float32).tolist()],
            n_results=min(limit, count),
            where=where,
            include=["distances"],
        )
        ids, distances = found["ids"][0], found["distances"][0]
        return [(int(i), 1.0 - float(d)) for i, d in zip(ids, distances, strict=True)]

    @staticmethod
    def _put(collection: Any, items: Sequence[tuple[int, np.ndarray]]) -> None:
        for start in range(0, len(items), 1000):
            chunk = items[start : start + 1000]
            collection.upsert(
                ids=[str(i) for i, _ in chunk],
                embeddings=[v.astype(np.float32).tolist() for _, v in chunk],
                metadatas=[{"ref_id": int(i)} for i, _ in chunk],
            )


class MeaningIndex:
    """Vectors per (kind, id): "memory" rows and "history" rows, computed on demand.

    The store opens on first use (importing ChromaDB takes about a second), in a worker thread.
    """

    def __init__(self, db: Database, embedder: Embedder, chroma_dir: Path | None = None) -> None:
        self._db = db
        self._embedder = embedder
        self._chroma_dir = chroma_dir
        self._store: VectorStore | None = None
        self._lock = asyncio.Lock()
        self._open_lock = threading.Lock()  # the warm-up thread and a first search may race
        self.backend = ""

    def open(self) -> VectorStore:
        """Open the store now (blocking). Safe to call from a warm-up thread."""
        with self._open_lock:
            return self._open()

    def _open(self) -> VectorStore:
        if self._store is None:
            legacy = SqliteVectors(self._db)
            store: VectorStore = legacy
            if self._chroma_dir is not None:
                try:
                    store = ChromaVectors(self._chroma_dir, legacy)
                except Exception:
                    log.exception("ChromaDB could not open; using the SQLite vectors")
            self.backend = "chromadb" if isinstance(store, ChromaVectors) else "sqlite"
            self._store = store
        return self._store

    async def _ready(self) -> VectorStore:
        if self._store is None:
            await asyncio.to_thread(self.open)
        assert self._store is not None
        return self._store

    async def sync(self, kind: str, items: Sequence[tuple[int, str]]) -> None:
        """Embed the items that have no vector yet; drop vectors of items no longer listed."""
        await self._update(kind, items, prune=True)

    async def add(self, kind: str, items: Sequence[tuple[int, str]]) -> None:
        """Embed the items that have no vector yet, and keep every other vector."""
        await self._update(kind, items, prune=False)

    async def prune(self, kind: str, keep: Sequence[int]) -> None:
        """Drop the vectors of items that no longer exist (forgotten or expired commands)."""
        store = await self._ready()
        model = self._embedder.model
        async with self._lock:
            have = await asyncio.to_thread(store.ids, kind, model)
            stale = sorted(have - set(keep))
            await asyncio.to_thread(store.delete, kind, model, stale)

    async def _update(self, kind: str, items: Sequence[tuple[int, str]], *, prune: bool) -> None:
        store = await self._ready()
        model = self._embedder.model
        async with self._lock:
            have = await asyncio.to_thread(store.ids, kind, model)
            if prune:
                stale = sorted(have - {item_id for item_id, _ in items})
                await asyncio.to_thread(store.delete, kind, model, stale)
            missing = [(i, text) for i, text in items if i not in have]
            for start in range(0, len(missing), BATCH):
                chunk = missing[start : start + BATCH]
                vectors = await self._embedder.embed([DOCUMENT + text for _, text in chunk])
                pairs = [(i, v) for (i, _), v in zip(chunk, vectors, strict=True)]
                await asyncio.to_thread(store.put, kind, model, pairs)

    async def search(
        self, kind: str, query: str, among: Sequence[int] | None = None, limit: int = 5
    ) -> list[tuple[int, float]]:
        """(id, similarity) best first, optionally only among some ids."""
        store = await self._ready()
        model = self._embedder.model
        if not await asyncio.to_thread(store.count, kind, model):
            return []
        query_vector = (await self._embedder.embed([QUERY + query]))[0]
        return await asyncio.to_thread(store.nearest, kind, model, query_vector, among, limit)
