"""fetch_page: download a web page and keep only its readable text (trafilatura).

The page is outside content, so the result is untrusted. Addresses on this computer or the local
network are blocked, also through redirects, so a page cannot point Jarvis at a router admin page
or a local service. The policy gate adds one more rule because this tool sends requests to
addresses the model picks (see `egress` in tools/policy.py).
"""

from __future__ import annotations

import asyncio
import io
import ipaddress
import logging
import re
import socket
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from jarvis import __version__
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.web.browser import normalize_url

log = logging.getLogger(__name__)

MAX_REDIRECTS = 5
# Many sites turn away clients that do not look like a browser; the Jarvis token stays visible.
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
    f"Chrome/130.0 Safari/537.36 Jarvis/{__version__}"
)
_HTML = {"text/html", "application/xhtml+xml"}
_TEXT = {"text/plain", "text/markdown", "text/csv", "application/json"}
_PDF = "application/pdf"
_BLANK_LINES = re.compile(r"\n{3,}")


@dataclass(frozen=True)
class Download:
    url: str
    content_type: str
    body: bytes
    encoding: str | None
    cut_off: bool = False


async def addresses(host: str, port: int) -> list[str]:
    """IP addresses a host name resolves to (a seam for tests)."""
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


async def check_url(url: str) -> str | None:
    """Why this address may not be fetched, or None if it may."""
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        return "only http and https web pages can be read"
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    try:
        found = await addresses(parsed.hostname, port)
    except OSError:
        return None  # unknown host: the download fails with a clear message instead
    for text in found:
        ip = ipaddress.ip_address(text.split("%")[0])
        if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
            ip = ip.ipv4_mapped
        if not ip.is_global:
            return "addresses on this computer or the local network cannot be read"
    return None


async def download(http: httpx.AsyncClient, url: str, max_bytes: int) -> Download:
    """GET a page, following redirects by hand so every hop is checked."""
    current = url
    headers = {
        "User-Agent": BROWSER_UA,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
    }
    for _ in range(MAX_REDIRECTS + 1):
        try:
            async with http.stream(
                "GET", current, headers=headers, follow_redirects=False, timeout=15
            ) as response:
                if response.is_redirect:
                    target = urljoin(current, response.headers.get("location", ""))
                    problem = await check_url(target)
                    if problem:
                        raise ToolError(f"The page redirected to {target}, but {problem}.")
                    current = target
                    continue
                if response.status_code >= 400:
                    raise ToolError(f"The site answered with error {response.status_code}.")
                content_type = response.headers.get("content-type", "").split(";")[0].strip()
                body = bytearray()
                cut_off = False
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > max_bytes:
                        cut_off = True
                        break
                return Download(
                    url=str(response.url),
                    content_type=content_type.lower(),
                    body=bytes(body[:max_bytes]),
                    encoding=response.charset_encoding,
                    cut_off=cut_off,
                )
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            raise ToolError(
                "I couldn't reach that site. Check the address or the internet connection."
            ) from exc
        except httpx.TimeoutException as exc:
            raise ToolError("The site took too long to answer.") from exc
        except httpx.HTTPError as exc:
            raise ToolError(f"Downloading the page failed ({type(exc).__name__}).") from exc
    raise ToolError("The page redirected too many times.")


def readable_text(page: Download) -> tuple[str, str]:
    """(title, text) of a downloaded page. Raises ToolError for content that is not text."""
    kind = page.content_type
    looks_html = page.body.lstrip()[:200].lower().startswith((b"<!doctype html", b"<html"))
    if kind in _HTML or (not kind and looks_html):
        return _html_text(page)
    if kind in _TEXT or kind.startswith("text/"):
        return "", page.body.decode(page.encoding or "utf-8", errors="replace")
    if kind == _PDF:
        if page.cut_off:
            raise ToolError("That PDF is too large to read.")
        return _pdf_text(page.body)
    raise ToolError(f"That link is a {kind or 'binary'} file, not a page I can read.")


def _html_text(page: Download) -> tuple[str, str]:
    import trafilatura

    document: Any = trafilatura.bare_extraction(
        page.body,
        url=page.url,
        include_comments=False,
        include_tables=True,
        with_metadata=True,
    )
    if document is None:
        return "", ""
    title = getattr(document, "title", None) or ""
    text = getattr(document, "text", None) or ""
    return str(title), str(text)


def _pdf_text(body: bytes) -> tuple[str, str]:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError

    try:
        reader = PdfReader(io.BytesIO(body))
        title = (reader.metadata.title if reader.metadata else None) or ""
        text = "\n".join(page.extract_text() or "" for page in reader.pages[:30])
    except (PdfReadError, ValueError) as exc:
        raise ToolError("That PDF could not be read.") from exc
    return title, text


@tool(
    risk=Risk.SAFE,
    sensitivity=Sensitivity.PUBLIC,
    untrusted=True,
    egress=True,
    timeout_s=25,
)
async def fetch_page(ctx: ToolContext, url: str) -> ToolResult:
    """Read the text of a web page, for example to summarize an article the user names.

    Args:
        url: The page address, for example "https://example.com/article".
    """
    cfg = ctx.settings.web
    page = await download(ctx.services.data.api.http, url, int(cfg.fetch_max_mb * 1024 * 1024))
    title, text = await asyncio.to_thread(readable_text, page)
    text = _BLANK_LINES.sub("\n\n", text).strip()
    if not text:
        raise ToolError("That page has no readable text. It may need JavaScript to show anything.")
    data: dict[str, Any] = {"url": page.url, "title": title, "text": text[: cfg.fetch_max_chars]}
    if len(text) > cfg.fetch_max_chars or page.cut_off:
        data["truncated"] = True
    log.info("Fetched %s (%d characters)", page.url, len(text))
    return ToolResult.success(data=data)


@fetch_page.preparer
async def _prepare_fetch(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    url = normalize_url(args["url"])
    problem = await check_url(url)
    if problem:
        return Prepared(args={"url": url}, summary=f"Read {url}", risk=Risk.BLOCKED, reason=problem)
    return Prepared(args={"url": url}, summary=f"Read the web page {url}")
