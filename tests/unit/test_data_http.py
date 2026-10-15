"""The data API plumbing: rate limits, circuit breakers, the SQLite cache, and error mapping."""

from __future__ import annotations

import httpx
import pytest

from jarvis.storage.db import Database
from jarvis.tools.data.http import (
    ApiCache,
    ApiClient,
    CircuitBreaker,
    ProviderError,
    TokenBucket,
    explain_failure,
)
from tests.conftest import FakeWeb


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def test_token_bucket_allows_bursts_then_refills() -> None:
    clock = Clock()
    bucket = TokenBucket(per_minute=8, clock=clock)  # bursts of 2, one more every 7.5 s
    assert [bucket.take() for _ in range(3)] == [True, True, False]
    clock.now += 7.5
    assert bucket.take() is True
    assert bucket.take() is False


def test_circuit_breaker_opens_then_lets_one_trial_through() -> None:
    clock = Clock()
    breaker = CircuitBreaker(threshold=3, cooldown_s=60, clock=clock)
    assert [breaker.record(False) for _ in range(3)] == [False, False, True]
    assert breaker.is_open
    clock.now += 61
    assert not breaker.is_open  # one trial request may go
    assert breaker.record(False) is True  # it failed: open again
    clock.now += 61
    breaker.record(True)
    assert not breaker.is_open


def test_cache_expires() -> None:
    clock = Clock()
    cache = ApiCache(Database(":memory:"), clock=clock)
    cache.put("quote:AAPL", {"price": 1}, ttl_s=60)
    assert cache.get("quote:AAPL") == {"price": 1}
    clock.now += 61
    assert cache.get("quote:AAPL") is None


def client(web: FakeWeb) -> ApiClient:
    http = httpx.AsyncClient(transport=httpx.MockTransport(web.handle))
    return ApiClient(Database(":memory:"), http=http)


async def test_no_network_is_offline_and_does_not_trip_the_breaker(web: FakeWeb) -> None:
    api = client(web)
    for _ in range(5):
        with pytest.raises(ProviderError) as caught:
            await api.get_json("frankfurter", "https://api.frankfurter.dev/v1/latest")
        assert caught.value.offline
    web.route("api.frankfurter.dev/v1/latest", {"rates": {}})
    assert await api.get_json("frankfurter", "https://api.frankfurter.dev/v1/latest") == {
        "rates": {}
    }


async def test_repeated_errors_skip_the_provider(web: FakeWeb) -> None:
    web.route("finnhub.io", status=500, content=b"oops")
    api = client(web)
    for _ in range(3):
        with pytest.raises(ProviderError, match="HTTP 500"):
            await api.get_json("finnhub", "https://finnhub.io/api/v1/quote")
    with pytest.raises(ProviderError, match="skipped"):
        await api.get_json("finnhub", "https://finnhub.io/api/v1/quote")
    assert web.hits("finnhub.io") == 3


async def test_not_found_is_a_miss_not_a_failure(web: FakeWeb) -> None:
    web.route("finnhub.io", status=404, json={"error": "no"})
    api = client(web)
    for _ in range(4):
        with pytest.raises(ProviderError) as caught:
            await api.get_json("finnhub", "https://finnhub.io/api/v1/quote")
        assert caught.value.miss
    assert web.hits("finnhub.io") == 4


async def test_cached_answers_skip_the_network(web: FakeWeb) -> None:
    web.route("api.frankfurter.dev", {"rates": {"INR": 95.0}})
    api = client(web)

    async def fetch() -> object:
        return await api.get_json("frankfurter", "https://api.frankfurter.dev/v1/latest")

    first = await api.cached("fx:USD", 3600, fetch)
    second = await api.cached("fx:USD", 3600, fetch)
    assert first == second == {"rates": {"INR": 95.0}}
    assert web.hits("api.frankfurter.dev") == 1


def test_explain_failure() -> None:
    offline = ProviderError("a", "x", offline=True)
    miss = ProviderError("b", "x", miss=True)
    broken = ProviderError("c", "x")
    assert "can't reach the internet" in explain_failure([offline, offline], "the price")
    assert "None of the data providers had" in explain_failure([miss], "the price")
    assert "not answering" in explain_failure([offline, broken], "the price")
