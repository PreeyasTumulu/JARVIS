"""Vectors in ChromaDB, copied once from SQLite, with SQLite as the fallback (ADR-084)."""

from __future__ import annotations

import socket
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import pytest

from jarvis.core.meaning import ChromaVectors, Embedder, MeaningIndex, SqliteVectors
from jarvis.storage.db import Database
from tests.unit.test_recall_briefing import FakeEmbeddings

pytest.importorskip("chromadb")

MODEL = "nomic"


def unit(*values: float) -> np.ndarray:
    v = np.array(values, dtype=np.float32)
    return v / np.linalg.norm(v)


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> list[Any]:
    """Fail any outside connection (ChromaDB's telemetry must stay off)."""
    tried: list[Any] = []
    real = socket.socket.connect

    def connect(self: socket.socket, address: Any) -> Any:
        if isinstance(address, tuple) and address[0] not in ("127.0.0.1", "::1", "localhost"):
            tried.append(address)
            raise OSError("no network in tests")
        return real(self, address)

    monkeypatch.setattr(socket.socket, "connect", connect)
    return tried


def test_vectors_are_copied_from_sqlite_once(tmp_path: Path, no_network: list[Any]) -> None:
    db = Database(":memory:")
    legacy = SqliteVectors(db)
    legacy.put("memory", MODEL, [(1, unit(1, 0, 0)), (2, unit(0, 1, 0))])

    store = ChromaVectors(tmp_path / "chroma", legacy)
    assert store.ids("memory", MODEL) == {1, 2}
    assert store.nearest("memory", MODEL, unit(0.9, 0.1, 0), None, 1)[0][0] == 1

    legacy.put("memory", MODEL, [(3, unit(0, 0, 1))])  # written to SQLite after the copy
    reopened = ChromaVectors(tmp_path / "chroma", legacy)
    assert reopened.ids("memory", MODEL) == {1, 2}  # the copy happens only into an empty store
    assert no_network == []


def test_search_among_some_ids_and_delete(tmp_path: Path, no_network: list[Any]) -> None:
    store = ChromaVectors(tmp_path / "chroma")
    store.put("history", MODEL, [(1, unit(1, 0)), (2, unit(0.9, 0.1)), (3, unit(0, 1))])
    found = store.nearest("history", MODEL, unit(1, 0), among=[2, 3], limit=5)
    assert [i for i, _ in found] == [2, 3]
    assert found[0][1] > 0.9  # similarity, not distance
    store.delete("history", MODEL, [2])
    assert store.ids("history", MODEL) == {1, 3}
    assert store.nearest("history", MODEL, unit(1, 0), among=[], limit=5) == []
    assert store.count("memory", MODEL) == 0  # a kind of its own
    assert no_network == []


def test_sqlite_is_used_when_chromadb_cannot_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(self: Any, *args: Any, **kwargs: Any) -> None:
        raise RuntimeError("chroma is broken")

    monkeypatch.setattr(ChromaVectors, "__init__", broken)
    index = MeaningIndex(Database(":memory:"), Embedder("http://x/v1", MODEL), tmp_path)
    assert isinstance(index.open(), SqliteVectors)
    assert index.backend == "sqlite"


async def test_memories_found_by_meaning_through_chromadb(
    tmp_path: Path, no_network: list[Any]
) -> None:
    fake = FakeEmbeddings()
    http = httpx.AsyncClient(transport=httpx.MockTransport(fake.handle))
    index = MeaningIndex(
        Database(":memory:"), Embedder("http://x/v1", MODEL, http=http), tmp_path / "chroma"
    )
    await index.sync("memory", [(1, "The user's manager is Ravi"), (2, "The car is a Swift")])
    assert index.backend == "chromadb"
    best = await index.search("memory", "who is my boss at the office", limit=1)
    assert best[0][0] == 1
    await index.sync("memory", [(2, "The car is a Swift")])  # 1 was forgotten
    assert [i for i, _ in await index.search("memory", "my boss")] == [2]
    assert no_network == []
