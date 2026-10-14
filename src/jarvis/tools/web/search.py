"""Web search. DuckDuckGo (ddgs) by default; SearXNG can plug in behind the same interface."""

from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass
from typing import Any, Protocol

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool


@dataclass(frozen=True)
class SearchHit:
    title: str
    url: str
    snippet: str


class SearchBackend(Protocol):
    async def search(self, query: str, max_results: int) -> list[SearchHit]: ...


class DuckDuckGoSearch:
    def __init__(self, region: str = "us-en") -> None:
        self._region = region

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        return await asyncio.to_thread(self._search, query, max_results)

    def _search(self, query: str, max_results: int) -> list[SearchHit]:
        from ddgs import DDGS
        from ddgs.exceptions import DDGSException

        try:
            raw: list[dict[str, Any]] = DDGS().text(
                query, region=self._region, max_results=max_results
            )
        except DDGSException as exc:
            raise ToolError(f"Web search failed: {exc}") from exc
        return [
            SearchHit(
                title=str(item.get("title", "")),
                url=str(item.get("href", "")),
                snippet=str(item.get("body", "")),
            )
            for item in raw or []
        ]


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, untrusted=True, timeout_s=20)
async def web_search(ctx: ToolContext, query: str) -> ToolResult:
    """Search the web and get the top results with titles, links and snippets.

    Use this for current events, facts you are unsure about, or anything that needs the internet.

    Args:
        query: What to search for, written as a search engine query.
    """
    hits = await ctx.services.search.search(query, ctx.settings.search.max_results)
    if not hits:
        return ToolResult.failure("The search returned no results.")
    return ToolResult.success(data=[asdict(hit) for hit in hits])
