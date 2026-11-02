"""The data service the tools share: the API client (cache, limits, breakers) and market data."""

from __future__ import annotations

import os
from collections.abc import Mapping

import httpx

from jarvis.config import Settings
from jarvis.storage.db import Database
from jarvis.tools.data.http import ApiClient
from jarvis.tools.data.market import MarketData, SearchingProvider


class DataHub:
    def __init__(
        self,
        db: Database,
        settings: Settings,
        *,
        http: httpx.AsyncClient | None = None,
        yahoo: SearchingProvider | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self._env = os.environ if env is None else env
        self.api = ApiClient(db, http=http)
        self.market = MarketData(self.api, settings.market, yahoo=yahoo, env=self._env)

    def key(self, name: str) -> str:
        """An API key from .env, or "" when it is not set."""
        return self._env.get(name, "").strip()

    async def aclose(self) -> None:
        await self.api.aclose()
