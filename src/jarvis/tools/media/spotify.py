"""Play music on Spotify: "play lofi beats on spotify", "play the album Random Access Memories".

Spotify's Web API finds the track, album, playlist, or artist (ADR-091): a free developer app,
with SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env, no login and no Premium. The song
request goes to Spotify, which is public data; the tool counts as egress, so a request made
right after private content asks first. The desktop app then opens it with a spotify: link
and Jarvis presses play on Spotify's own media session (not the play and pause toggle).

Whether that play starts the new item or resumes the old one is Spotify's behaviour, so Jarvis
checks what Spotify reports as playing and only says "Playing ..." when it matches. Without
the keys, Spotify's own search opens for the words.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
from dataclasses import dataclass
from typing import Any, Literal
from urllib.parse import quote

from jarvis.adapters.http import ApiClient, ProviderError
from jarvis.platform import media
from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

log = logging.getLogger(__name__)

TOKEN_URL = "https://accounts.spotify.com/api/token"
SEARCH_URL = "https://api.spotify.com/v1/search"
PROVIDER = "spotify"
KEYS = ("SPOTIFY_CLIENT_ID", "SPOTIFY_CLIENT_SECRET")
SESSION_WAIT_S = 8.0  # Spotify's media session appears a few seconds after a cold start
PLAYING_WAIT_S = 4.0
Kind = Literal["auto", "track", "album", "playlist", "artist"]
_KIND_WORDS = re.compile(r"\b(playlist|album|artist|song|track)\b", re.I)


@dataclass(frozen=True)
class Found:
    kind: str
    name: str
    by: str
    uri: str


_token: tuple[str, float] | None = None  # (access token, expiry on the monotonic clock)


async def access_token(api: ApiClient) -> str:
    """A client-credentials token (search only, no user), kept until shortly before it ends."""
    global _token
    if _token is not None and _token[1] > time.monotonic() + 60:
        return _token[0]
    client_id, secret = api.key(KEYS[0]), api.key(KEYS[1])
    basic = base64.b64encode(f"{client_id}:{secret}".encode()).decode()

    async def request() -> Any:
        response = await api.http.post(
            TOKEN_URL,
            data={"grant_type": "client_credentials"},
            headers={"Authorization": f"Basic {basic}"},
        )
        if response.status_code in (400, 401):
            raise ProviderError(PROVIDER, "the client ID or secret in .env was refused")
        if response.status_code >= 400:
            raise ProviderError(PROVIDER, f"HTTP {response.status_code}")
        return response.json()

    payload = await api.call(PROVIDER, request)
    _token = (str(payload["access_token"]), time.monotonic() + float(payload["expires_in"]))
    return _token[0]


def wanted_kind(query: str, kind: Kind) -> str:
    if kind != "auto":
        return kind
    word = _KIND_WORDS.search(query)
    if word is None:
        return "track"
    return "track" if word[1].casefold() in ("song", "track") else word[1].casefold()


def clean_query(query: str) -> str:
    text = re.sub(r"\b(on|in|from)\s+spotify\b", " ", query, flags=re.I)
    text = re.sub(r"^\s*(play|put on|start)\s+", "", text, flags=re.I)
    text = re.sub(r"\b(the\s+)?(playlist|album|artist|song|track)\b", " ", text, flags=re.I)
    return " ".join(text.split())


def pick(payload: dict[str, Any], kind: str) -> Found | None:
    """The first usable result of the wanted kind (Spotify ranks them well)."""
    items = [item for item in (payload.get(f"{kind}s") or {}).get("items") or [] if item]
    for item in items:
        if not item.get("uri"):
            continue
        if kind in ("track", "album"):
            by = ", ".join(a.get("name", "") for a in item.get("artists") or [])
        elif kind == "playlist":
            by = (item.get("owner") or {}).get("display_name") or ""
        else:
            by = ""
        return Found(kind, str(item.get("name") or ""), by, str(item["uri"]))
    return None


async def search(api: ApiClient, query: str, kind: str, market: str) -> Found | None:
    token = await access_token(api)
    data = await api.get_json(
        PROVIDER,
        SEARCH_URL,
        params={"q": query, "type": kind, "limit": 5, "market": market},
        headers={"Authorization": f"Bearer {token}"},
    )
    return pick(data, kind)


def open_uri(uri: str) -> None:
    os.startfile(uri)  # type: ignore[attr-defined,unused-ignore]  # Spotify's link handler


async def _wait_for_session() -> bool:
    deadline = time.monotonic() + SESSION_WAIT_S
    while time.monotonic() < deadline:
        if await media.app_state(PROVIDER) is not None:
            return True
        await asyncio.sleep(0.5)
    return False


def _matches(state: media.MediaState | None, found: Found, before: media.MediaState | None) -> bool:
    if state is None or state.status != "playing":
        return False
    if found.kind == "track":
        return found.name.casefold() in state.title.casefold()
    return before is None or (state.title, state.artist) != (before.title, before.artist)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, egress=True, timeout_s=40)
async def play_spotify(ctx: ToolContext, query: str, kind: Kind = "auto") -> ToolResult:
    """Find music on Spotify and play it in the Spotify app, for "play lofi beats on spotify",
    "play the album Discovery", or "play my chill playlist". For pause, next, or resume use
    media_control.

    Args:
        query: What to play, in the user's words: a song, artist, album, or playlist.
        kind: "track", "album", "playlist", or "artist"; "auto" decides from the words.
    """
    words = clean_query(query) or query
    api = ctx.services.data.api
    if not all(api.key(name) for name in KEYS):
        await asyncio.to_thread(open_uri, f"spotify:search:{quote(words)}")
        return ToolResult.success(
            data={"searched": words, "keys": False},
            speech=f"I opened Spotify's search for {words}. Add SPOTIFY_CLIENT_ID and "
            "SPOTIFY_CLIENT_SECRET to .env and I can pick and play it for you.",
        )
    chosen_kind = wanted_kind(query, kind)
    try:
        found = await search(api, words, chosen_kind, ctx.settings.spotify.market)
    except ProviderError as exc:
        raise ToolError(f"Spotify search failed: {exc}") from exc
    if found is None:
        raise ToolError(f"Spotify has no {chosen_kind} matching '{words}'.")
    before = await media.app_state(PROVIDER)
    await asyncio.to_thread(open_uri, found.uri)
    label = f"{found.name} by {found.by}" if found.by else found.name
    data: dict[str, Any] = {"kind": found.kind, "name": found.name, "by": found.by}
    data["uri"] = found.uri
    if not await _wait_for_session():
        return ToolResult.success(
            data, speech=f"I opened {label} in Spotify. Press play if it doesn't start."
        )
    await media.play_app(PROVIDER)
    deadline = time.monotonic() + PLAYING_WAIT_S
    while time.monotonic() < deadline:
        state = await media.app_state(PROVIDER)
        if _matches(state, found, before):
            data["playing"] = True
            return ToolResult.success(data, speech=f"Playing {label} on Spotify.")
        await asyncio.sleep(0.4)
    data["playing"] = False
    return ToolResult.success(
        data, speech=f"I opened {label} in Spotify. If it isn't playing yet, press play on it."
    )
