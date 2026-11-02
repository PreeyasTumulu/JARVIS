"""Open web pages in the default browser. Only http and https links are allowed."""

from __future__ import annotations

import asyncio
import re
import webbrowser
from typing import Any
from urllib.parse import urlparse

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolResult
from jarvis.tools.registry import tool

_LOOKS_LIKE_DOMAIN = re.compile(r"^[\w.-]+\.[a-z]{2,}(/.*)?$", re.IGNORECASE)


def normalize_url(text: str) -> str:
    url = text.strip()
    if "://" not in url and _LOOKS_LIKE_DOMAIN.match(url):
        url = f"https://{url}"
    return url


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=15, egress=True)
async def open_url(ctx: ToolContext, url: str) -> ToolResult:
    """Open a web page in the default browser.

    Args:
        url: The address, for example "github.com" or "https://python.org/downloads".
    """
    await asyncio.to_thread(webbrowser.open, url)
    host = urlparse(url).hostname or url
    return ToolResult.success(data={"opened": url}, speech=f"Opening {host}.")


@open_url.preparer
async def _prepare_open_url(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    url = normalize_url(args["url"])
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return Prepared(
            args={"url": url},
            summary=f"Open {url}",
            risk=Risk.BLOCKED,
            reason="only http and https web addresses can be opened",
        )
    return Prepared(args={"url": url}, summary=f"Open {url} in the browser")
