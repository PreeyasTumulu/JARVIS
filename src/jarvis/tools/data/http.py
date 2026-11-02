"""Shared plumbing for the data APIs: one HTTP client, a SQLite cache, rate limits, breakers.

Each provider gets a token bucket (requests per minute) and a circuit breaker. A provider over its
limit, or one that failed three times in a row, is skipped for a while instead of slowing every
question down, and the caller moves on to the next provider in its chain. Network failures (no
connection at all) do not count against a breaker, so providers work again as soon as the
connection is back.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable, Mapping, Sequence
from typing import Any, TypeVar

import httpx

from jarvis import __version__
from jarvis.storage.db import Database

log = logging.getLogger(__name__)

T = TypeVar("T")

USER_AGENT = f"Jarvis/{__version__} (+https://github.com/PreeyasTumulu/JARVIS)"
CONNECTIVITY_URL = "http://www.msftconnecttest.com/connecttest.txt"  # Windows network check

# Requests per minute Jarvis allows itself, a little under each free tier.
RATE_PER_MINUTE: dict[str, float] = {
    "finnhub": 50,
    "twelvedata": 7,
    "alphavantage": 4,  # the free tier is 25 a day; its "limit reached" reply trips the breaker
    "yfinance": 30,
    "coingecko": 20,
    "frankfurter": 60,
    "er-api": 20,
    "open-meteo": 60,
}
DEFAULT_RATE = 30.0
FAILURES_TO_OPEN = 3
BREAKER_COOLDOWN_S = 300.0

_OFFLINE = (httpx.ConnectError, httpx.ConnectTimeout, httpx.ProxyError)


class ProviderError(Exception):
    """A provider could not answer.

    `offline` means the network itself failed (no connection, no DNS). `miss` means the provider
    works but has no data for this request; neither counts against the circuit breaker.
    """

    def __init__(
        self, provider: str, message: str, *, offline: bool = False, miss: bool = False
    ) -> None:
        super().__init__(f"{provider}: {message}")
        self.provider = provider
        self.offline = offline
        self.miss = miss


def explain_failure(errors: Sequence[ProviderError], what: str) -> str:
    """One sentence for the user when every provider in a chain failed."""
    if errors and all(error.offline for error in errors):
        return f"I can't reach the internet right now, so I couldn't get {what}."
    if errors and all(error.miss for error in errors):
        return f"None of the data providers had {what}."
    if not errors:
        return f"No configured data provider can get {what}."
    return f"The data providers are not answering right now, so I couldn't get {what}."


class TokenBucket:
    """Allows `per_minute` requests on average, with short bursts."""

    def __init__(self, per_minute: float, clock: Callable[[], float] = time.monotonic) -> None:
        self.capacity = max(1.0, per_minute / 4)
        self.rate = per_minute / 60.0
        self.tokens = self.capacity
        self._clock = clock
        self._updated = clock()

    def take(self) -> bool:
        now = self._clock()
        self.tokens = min(self.capacity, self.tokens + (now - self._updated) * self.rate)
        self._updated = now
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False


class CircuitBreaker:
    """Opens after repeated failures. After the cooldown one trial request is let through."""

    def __init__(
        self,
        threshold: int = FAILURES_TO_OPEN,
        cooldown_s: float = BREAKER_COOLDOWN_S,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._threshold = threshold
        self._cooldown_s = cooldown_s
        self._clock = clock
        self._failures = 0
        self._opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self._opened_at is None:
            return False
        return self._clock() - self._opened_at < self._cooldown_s

    def record(self, ok: bool) -> bool:
        """Record a result. Returns True when this failure just opened the breaker."""
        if ok:
            self._failures = 0
            self._opened_at = None
            return False
        self._failures += 1
        if self._failures >= self._threshold:
            just_opened = not self.is_open
            self._opened_at = self._clock()
            return just_opened
        return False


class ApiCache:
    """JSON values in SQLite with an expiry time, so answers also survive restarts."""

    def __init__(self, db: Database, clock: Callable[[], float] = time.time) -> None:
        self._db = db
        self._clock = clock
        db.execute("DELETE FROM api_cache WHERE expires_at < ?", (clock(),))

    def get(self, key: str) -> Any | None:
        rows = self._db.execute(
            "SELECT value_json FROM api_cache WHERE key = ? AND expires_at >= ?",
            (key, self._clock()),
        )
        return json.loads(rows[0]["value_json"]) if rows else None

    def put(self, key: str, value: Any, ttl_s: float) -> None:
        now = self._clock()
        self._db.execute(
            "INSERT INTO api_cache (key, value_json, fetched_at, expires_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json, "
            "fetched_at = excluded.fetched_at, expires_at = excluded.expires_at",
            (key, json.dumps(value), now, now + ttl_s),
        )


class ApiClient:
    def __init__(
        self,
        db: Database,
        *,
        http: httpx.AsyncClient | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.cache = ApiCache(db)
        self._http = http
        self._clock = clock
        self._buckets: dict[str, TokenBucket] = {}
        self._breakers: dict[str, CircuitBreaker] = {}

    @property
    def http(self) -> httpx.AsyncClient:
        """The shared client, created on first use."""
        if self._http is None:
            self._http = httpx.AsyncClient(
                timeout=httpx.Timeout(8.0, connect=4.0),
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            )
        return self._http

    async def aclose(self) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def call(self, provider: str, request: Callable[[], Awaitable[T]]) -> T:
        """Run one provider request under its rate limit and circuit breaker."""
        breaker = self._breakers.setdefault(provider, CircuitBreaker(clock=self._clock))
        if breaker.is_open:
            raise ProviderError(provider, "skipped for a few minutes after repeated failures")
        bucket = self._buckets.setdefault(
            provider, TokenBucket(RATE_PER_MINUTE.get(provider, DEFAULT_RATE), clock=self._clock)
        )
        if not bucket.take():
            raise ProviderError(provider, "skipped to stay under its rate limit")
        try:
            result = await request()
        except ProviderError as exc:
            if not exc.offline:
                self._record(provider, breaker, ok=exc.miss)
            raise
        except Exception as exc:
            self._record(provider, breaker, ok=False)
            raise ProviderError(provider, f"failed ({type(exc).__name__})") from exc
        self._record(provider, breaker, ok=True)
        return result

    async def get_json(
        self,
        provider: str,
        url: str,
        *,
        params: Mapping[str, Any] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET a JSON document. Query parameters are never logged, since some carry API keys."""

        async def request() -> Any:
            log.info("GET %s %s", provider, url)
            try:
                response = await self.http.get(url, params=params, headers=headers)
            except _OFFLINE as exc:
                raise ProviderError(provider, "could not connect", offline=True) from exc
            except httpx.HTTPError as exc:
                raise ProviderError(provider, f"request failed ({type(exc).__name__})") from exc
            status = response.status_code
            if status == 429:
                raise ProviderError(provider, "rate limited by the provider")
            if status in (400, 404, 422):
                raise ProviderError(provider, f"no data (HTTP {status})", miss=True)
            if status >= 400:
                raise ProviderError(provider, f"HTTP {status}")
            try:
                return response.json()
            except ValueError as exc:
                raise ProviderError(provider, "answered with something that is not JSON") from exc

        return await self.call(provider, request)

    async def online(self) -> bool:
        """Whether the internet is reachable at all, using the URL Windows itself checks."""
        try:
            await self.http.get(CONNECTIVITY_URL, timeout=3)
        except httpx.HTTPError:
            return False
        return True

    async def explain(self, errors: Sequence[ProviderError], what: str) -> str:
        """Like explain_failure, but checks the connection when an error does not say offline.

        yfinance hides a dead connection behind unrelated errors, so "not answering" would be
        wrong when the real cause is no internet.
        """
        unclear = any(not (error.offline or error.miss) for error in errors)
        if unclear and not await self.online():
            return f"I can't reach the internet right now, so I couldn't get {what}."
        return explain_failure(errors, what)

    async def cached(self, key: str, ttl_s: float, produce: Callable[[], Awaitable[Any]]) -> Any:
        """Return the cached value for `key`, or produce, store, and return a fresh one."""
        hit = self.cache.get(key)
        if hit is not None:
            log.info("cache hit %s", key)
            return hit
        value = await produce()
        self.cache.put(key, value, ttl_s)
        return value

    def _record(self, provider: str, breaker: CircuitBreaker, *, ok: bool) -> None:
        if breaker.record(ok):
            log.warning(
                "%s failed %d times in a row; skipping it for %.0f s",
                provider,
                FAILURES_TO_OPEN,
                BREAKER_COOLDOWN_S,
            )
