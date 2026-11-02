"""Browser step tools: open a page, read it, click something, type into a field.

The model chains these one step at a time (ADR-038), so every step goes through the policy gate
on its own and shows up in the tool log. Pages are outside content (untrusted), and because the
profile may be signed in somewhere, what they show is private (fail closed).

Rules: only public http and https addresses; never WhatsApp (send_whatsapp has its own profile);
pressing Enter in a form or clicking something that submits, buys, or deletes asks first; typing
passwords, card numbers, or one-time codes is blocked. Opening and typing send what the model
chose to a website, so they are `egress` tools (policy.py).
"""

from __future__ import annotations

import asyncio
import re
from operator import attrgetter
from typing import Any
from urllib.parse import urlparse

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.browser.session import BrowserPage, PageElement, PageSnapshot
from jarvis.tools.naming import pick
from jarvis.tools.registry import tool
from jarvis.tools.ui.guard import target_risk
from jarvis.tools.web.browser import normalize_url
from jarvis.tools.web.fetch import check_url

BRIEF_CHARS = 800  # page text returned after a click or typing; browser_read returns more
BRIEF_ELEMENTS = 25
MAX_TYPE_CHARS = 2000
SEARCH_BOX_TRIES = 4
_TARGET = re.compile(r"^\s*#?(\d+)\b\s*(.*)$")
_WHATSAPP = re.compile(r"(^|\.)(whatsapp\.(com|net)|wa\.me)$", re.IGNORECASE)
SENSITIVE_AUTOCOMPLETE = {
    "current-password",
    "new-password",
    "one-time-code",
    "cc-number",
    "cc-csc",
    "cc-exp",
    "cc-exp-month",
    "cc-exp-year",
}
_SENSITIVE_LABEL = re.compile(
    r"\b(password|passcode|pin|otp|one[- ]time|cvv|cvc|security code|card number)\b",
    re.IGNORECASE,
)
SENSITIVE_REASON = "Jarvis never types passwords, card numbers, or one-time codes"
# Small models take "Opened Wikipedia." as the end of the job and then claim the search too.
NEXT_STEP_HINT = (
    "(If the user's request needs more on this page, call browser_type or browser_click now "
    "with an element number. Otherwise reply in one or two short spoken sentences, no lists. "
    "Never say a step is done unless a tool result shows it.)"
)


def page_data(snap: PageSnapshot, *, excerpt: bool = False) -> dict[str, Any]:
    """What the model gets: controls before text, so a long page is cut in the text.

    After open, click, and type the text is an "excerpt": the task usually goes on, and the
    executor's "answer in two or three sentences" hint for long text would end it early.
    """
    data: dict[str, Any] = {
        "title": snap.title,
        "url": snap.url,
        "elements": [element.describe() for element in snap.elements],
        "excerpt" if excerpt else "text": snap.text,
    }
    if snap.truncated:
        data["truncated"] = True
    return data


async def current_page(ctx: ToolContext) -> BrowserPage:
    page = await ctx.services.browser.page("browser")
    if not page.url.startswith("http"):
        raise ToolError("Jarvis's browser has no page open. Use browser_open first.")
    return page


async def brief(ctx: ToolContext, page: BrowserPage) -> PageSnapshot:
    """A short look at the page after an action, refusing pages on this computer or network."""
    problem = await check_url(page.url) if page.url.startswith("http") else None
    if problem:
        url = page.url
        await page.blank()
        raise ToolError(f"The page went to {url}, but {problem}.")
    return await page.snapshot(BRIEF_CHARS, BRIEF_ELEMENTS)


async def find_element(page: BrowserPage, target: str, *, fields: bool = False) -> PageElement:
    """A control by its number from a page read ("12") or by its label ("Add to cart")."""
    snap = await page.snapshot(0, 0, everything=True)
    pool = [e for e in snap.elements if not fields or e.kind == "field"]
    numbered = _TARGET.match(target)
    if numbered:
        wanted = int(numbered.group(1))
        for element in pool:
            if element.id == wanted:
                return element
        raise ToolError(f"There is no {'field' if fields else 'control'} {wanted} on the page now.")
    best, rival = pick(target, pool, attrgetter("label"))
    if best is None:
        some = ", ".join([e.label for e in pool if e.label][:8]) or "none with a label"
        raise ToolError(f"Nothing on the page is called '{target}'. Some that are: {some}.")
    if rival is not None:
        raise ToolError(
            f"'{target}' could be {best.describe()} or {rival.describe()}. "
            "Ask the user which one, or use the number."
        )
    return best


async def same_element(page: BrowserPage, target: str, *, fields: bool = False) -> PageElement:
    """At run time: the element that was confirmed, still carrying the same label."""
    numbered = _TARGET.match(target)
    if not numbered:
        raise ToolError("That control is no longer known. Read the page again.")
    element = await find_element(page, numbered.group(1), fields=fields)
    if element.label != numbered.group(2).strip():
        raise ToolError("The page changed since then. Read it again before clicking or typing.")
    return element


def _host(url: str) -> str:
    return urlparse(url).hostname or url


def _preview(text: str, limit: int = 80) -> str:
    flat = " ".join(text.split())
    return flat if len(flat) <= limit else flat[: limit - 3] + "..."


@tool(
    risk=Risk.SAFE,
    sensitivity=Sensitivity.PRIVATE,
    untrusted=True,
    timeout_s=45,
    egress=True,
)
async def browser_open(ctx: ToolContext, url: str, search: str | None = None) -> ToolResult:
    """Open a web page in Jarvis's own browser to work with it (search, click, type). To just
    show the user a page, use open_url instead.

    Args:
        url: The address, for example "amazon.in" or "https://github.com/login".
        search: Only if the user wants to search that site: the words to search for.
    """
    page = await ctx.services.browser.page("browser")
    await page.goto(url, ctx.settings.browser.navigation_timeout_s)
    if search:
        # Small models rarely chain open then type, so the common case is one call. Only a
        # field that looks like a search box is submitted (the same rule as browser_type).
        box = await _search_box(page)
        await page.fill(box.id, search, True)
    snap = await brief(ctx, page)
    done = f"Searched {_host(url)} for {search}." if search else f"Opened {snap.title or url}."
    return ToolResult.success(data=page_data(snap, excerpt=True), speech=done, hint=NEXT_STEP_HINT)


@browser_open.preparer
async def _prepare_browser_open(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    url = normalize_url(args["url"])
    host = _host(url)
    problem = await check_url(url)
    if problem is None and _WHATSAPP.search(host):
        problem = "WhatsApp is only used through send_whatsapp, which reads the message back first"
    search = (args.get("search") or "").strip() or None
    if search and len(search) > MAX_TYPE_CHARS:
        raise ToolError(f"That search is more than {MAX_TYPE_CHARS} characters.")
    also = f' and search it for "{_preview(search)}"' if search else ""
    return Prepared(
        args={"url": url, "search": search},
        summary=f"Open {url} in Jarvis's browser{also}",
        risk=Risk.BLOCKED if problem else Risk.SAFE,
        reason=problem,
    )


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=20)
async def browser_read(ctx: ToolContext) -> ToolResult:
    """Read the page open in Jarvis's browser: its text and its numbered links, buttons, and
    fields (use the numbers with browser_click and browser_type)."""
    page = await current_page(ctx)
    settings = ctx.settings.browser
    snap = await page.snapshot(settings.read_max_chars, settings.max_elements)
    return ToolResult.success(data=page_data(snap))


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=30)
async def browser_click(ctx: ToolContext, target: str) -> ToolResult:
    """Click a link or button in Jarvis's browser.

    Args:
        target: The element's number from browser_read or browser_open (e.g. "12"), or its
            visible label (e.g. "Add to cart").
    """
    page = await current_page(ctx)
    element = await same_element(page, target)
    await page.click(element.id)
    page = await ctx.services.browser.page("browser")  # the link may have opened a new tab
    snap = await brief(ctx, page)
    return ToolResult.success(
        data=page_data(snap, excerpt=True),
        speech=f"Clicked {element.label}.",
        hint=NEXT_STEP_HINT,
    )


@browser_click.preparer
async def _prepare_browser_click(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    page = await current_page(ctx)
    element = await find_element(page, args["target"])
    if element.disabled:
        raise ToolError(f"{element.label or 'That control'} is greyed out on the page.")
    risk, reason = target_risk(element.label)
    if element.submit and not element.search and risk is Risk.SAFE:
        risk, reason = Risk.CONFIRM, "it submits a form on the page"
    if element.href:
        problem = await check_url(element.href) if element.href.startswith("http") else None
        if problem:
            risk, reason = Risk.BLOCKED, problem
    return Prepared(
        args={"target": element.target},
        summary=f"Click the {element.label or 'unlabelled'} {element.kind} on {_host(page.url)}",
        risk=risk,
        reason=reason,
    )


@tool(
    risk=Risk.SAFE,
    sensitivity=Sensitivity.PRIVATE,
    untrusted=True,
    timeout_s=30,
    egress=True,
)
async def browser_type(
    ctx: ToolContext, text: str, target: str | None = None, submit: bool = False
) -> ToolResult:
    """Type into a field on the page in Jarvis's browser, for example a search box.

    Args:
        text: The exact text to type. It replaces what the field held.
        target: The field's number or label. Leave empty for the page's search box.
        submit: True to press Enter afterwards, for example to run a search.
    """
    page = await current_page(ctx)
    element = await same_element(page, target or "", fields=True)
    await page.fill(element.id, text, submit)
    snap = await brief(ctx, page)
    done = "Searched." if submit and element.search else "Typed it."
    return ToolResult.success(data=page_data(snap, excerpt=True), speech=done)


@browser_type.preparer
async def _prepare_browser_type(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    text: str = args["text"]
    if not text:
        raise ToolError("There is no text to type.")
    if len(text) > MAX_TYPE_CHARS:
        raise ToolError(f"That is more than {MAX_TYPE_CHARS} characters.")
    page = await current_page(ctx)
    target = args.get("target")
    element = await (find_element(page, target, fields=True) if target else _main_field(page))
    submit = bool(args.get("submit"))
    risk, reason = Risk.SAFE, None
    if (
        element.password
        or element.autocomplete in SENSITIVE_AUTOCOMPLETE
        or _SENSITIVE_LABEL.search(element.label)
    ):
        risk, reason = Risk.BLOCKED, SENSITIVE_REASON
    elif element.disabled:
        raise ToolError(f"The {element.label or 'field'} is greyed out.")
    elif submit and not element.search:
        risk, reason = Risk.CONFIRM, "pressing Enter here submits a form"
    enter = " and press Enter" if submit else ""
    return Prepared(
        args={"text": text, "target": element.target, "submit": submit},
        summary=(
            f'Type "{_preview(text)}" into the {element.label or "unlabelled"} field on '
            f"{_host(page.url)}{enter}"
        ),
        risk=risk,
        reason=reason,
    )


async def _search_box(page: BrowserPage) -> PageElement:
    """The page's search box, giving a slow page a few seconds to show it."""
    for attempt in range(SEARCH_BOX_TRIES):
        snap = await page.snapshot(0, 0, everything=True)
        for element in snap.elements:
            if element.kind == "field" and element.search and not element.disabled:
                return element
        if attempt < SEARCH_BOX_TRIES - 1:
            await asyncio.sleep(1)
    raise ToolError(f"{_host(page.url)} has no search box I can find. Use browser_type.")


async def _main_field(page: BrowserPage) -> PageElement:
    """No field named: the page's search box, or its only text field."""
    snap = await page.snapshot(0, 0, everything=True)
    usable = [e for e in snap.elements if e.kind == "field" and not e.disabled]
    searches = [e for e in usable if e.search]
    if searches:
        return searches[0]
    if len(usable) == 1:
        return usable[0]
    if not usable:
        raise ToolError("There is no field to type in on this page.")
    names = ", ".join(e.describe() for e in usable[:6])
    raise ToolError(f"Which field? The page has: {names}.")
