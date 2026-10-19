"""Search a named website (YouTube, Wikipedia, Amazon, ...) and show its results page.

The local model does not reliably chain "open the site, find the search box, type, submit"
(RISKS.md R25), and "search youtube for lofi" became a general web search read aloud. Every
big site has a search address, so Jarvis builds it and opens it in your default browser (where
you are signed in). Sites can be added or changed under [search] sites in config.
"""

from __future__ import annotations

import asyncio
import webbrowser
from typing import Any
from urllib.parse import quote, quote_plus

from rapidfuzz import fuzz, process

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

# {q} is the query, form encoded (spaces as +); {p} is the query path encoded (spaces as %20).
SITES: dict[str, str] = {
    "youtube": "https://www.youtube.com/results?search_query={q}",
    "youtube music": "https://music.youtube.com/search?q={q}",
    "google": "https://www.google.com/search?q={q}",
    "google maps": "https://www.google.com/maps/search/{p}",
    "google images": "https://www.google.com/search?tbm=isch&q={q}",
    "google news": "https://news.google.com/search?q={q}",
    "wikipedia": "https://en.wikipedia.org/w/index.php?search={q}",
    "amazon": "https://www.amazon.in/s?k={q}",
    "flipkart": "https://www.flipkart.com/search?q={q}",
    "github": "https://github.com/search?q={q}",
    "reddit": "https://www.reddit.com/search/?q={q}",
    "stack overflow": "https://stackoverflow.com/search?q={q}",
    "spotify": "https://open.spotify.com/search/{p}",
    "x": "https://x.com/search?q={q}",
    "linkedin": "https://www.linkedin.com/search/results/all/?keywords={q}",
    "imdb": "https://www.imdb.com/find/?q={q}",
    "netflix": "https://www.netflix.com/search?q={q}",
    "duckduckgo": "https://duckduckgo.com/?q={q}",
    "pypi": "https://pypi.org/search/?q={q}",
    "npm": "https://www.npmjs.com/search?q={q}",
    "hugging face": "https://huggingface.co/search/full-text?q={q}",
    "swiggy": "https://www.swiggy.com/search?query={q}",
    "zomato": "https://www.zomato.com/search?q={q}",
}
ALIASES = {
    "yt": "youtube",
    "maps": "google maps",
    "wiki": "wikipedia",
    "twitter": "x",
    "stackoverflow": "stack overflow",
    "huggingface": "hugging face",
    "images": "google images",
    "news": "google news",
}
MATCH_THRESHOLD = 80


def known_sites(ctx: ToolContext) -> dict[str, str]:
    return {**SITES, **{k.casefold(): v for k, v in ctx.settings.search.sites.items()}}


def resolve_site(name: str, sites: dict[str, str]) -> str | None:
    wanted = " ".join(name.casefold().replace(".com", "").replace("www.", "").split())
    wanted = ALIASES.get(wanted, wanted)
    if wanted in sites:
        return wanted
    match = process.extractOne(wanted, list(sites), scorer=fuzz.WRatio)
    return str(match[0]) if match and match[1] >= MATCH_THRESHOLD else None


def search_address(template: str, query: str) -> str:
    return template.replace("{q}", quote_plus(query)).replace("{p}", quote(query, safe=""))


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=15, egress=True)
async def search_site(ctx: ToolContext, site: str, query: str) -> ToolResult:
    """Search one named website and show its results in the user's browser: "search youtube
    for lofi music", "look up Alan Turing on wikipedia", "find running shoes on amazon".
    Use this instead of web_search whenever the user names the site.

    Args:
        site: The website, for example "youtube", "wikipedia", "amazon", "github", "maps".
        query: What to search for on that site, for example "lofi music".
    """
    await asyncio.to_thread(webbrowser.open, ctx_url(ctx, site, query))
    return ToolResult.success(
        data={"site": site, "query": query}, speech=f"Here are the {site} results for {query}."
    )


def ctx_url(ctx: ToolContext, site: str, query: str) -> str:
    sites = known_sites(ctx)
    return search_address(sites[site], query)


@search_site.preparer
async def _prepare_search_site(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    query = " ".join(str(args["query"]).split())
    if not query:
        raise ToolError("There is nothing to search for. Ask the user what to look up.")
    sites = known_sites(ctx)
    site = resolve_site(str(args["site"]), sites)
    if site is None:
        names = ", ".join(sorted(sites)[:12])
        raise ToolError(
            f"I don't know how to search '{args['site']}'. I know {names}, and more. "
            "For another site, use browser_open with its address and search."
        )
    url = search_address(sites[site], query)
    return Prepared(args={"site": site, "query": query}, summary=f"Open {url}")
