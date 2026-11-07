"""The local API: JSON over HTTP and one WebSocket, for programs on this computer only.

`GET /` is the chat window (ADR-103, server/ui.py). What keeps other programs and websites out:

1. The server listens on 127.0.0.1 only (set in serve.py, not configurable).
2. The Host header must name this computer, which defeats DNS rebinding.
3. Browsers always send an Origin header with a WebSocket or a cross-site request and cannot
   leave it out, so any HTTP request that carries one is refused. The one browser the
   WebSocket accepts is the chat page itself: its exact Origin plus the UI token in the page.
4. The WebSocket for programs, the bridge, and `/mcp/` need the per-launch token, which
   `jarvis serve` writes to the data folder (only this Windows account can read it). The UI
   token is a different one, so the page can never call the bridge or `/mcp/`.

`/mcp/` offers Jarvis's public tools to MCP clients through `jarvis mcp serve` (ADR-085).

`GET /health` says only that Jarvis is up and which version, so a client can find it.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import secrets
from collections.abc import AsyncIterator, Sequence
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from jarvis import __version__
from jarvis.bridge.service import BridgeRequest
from jarvis.server import ui
from jarvis.server.hub import Client
from jarvis.server.mcp_server import McpGateway, mcp_app
from jarvis.server.runtime import Runtime

log = logging.getLogger(__name__)

LOCAL_HOSTS = ("127.0.0.1", "localhost")
POLICY_VIOLATION = 1008
HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}


def _not_allowed() -> JSONResponse:
    return JSONResponse({"error": "not allowed"}, status_code=403)


def _token_ok(sent: str | None, token: str | None) -> bool:
    return token is not None and sent is not None and secrets.compare_digest(sent, token)


def create_server(
    runtime: Runtime,
    *,
    token: str,
    hosts: Sequence[str] = LOCAL_HOSTS,
    bridge_token: str | None = None,
    mcp: McpGateway | None = None,
    ui_token: str | None = None,
    port: int | None = None,
) -> FastAPI:
    page_origins = ui.origins(port) if ui_token and port else frozenset()
    mounted = mcp_app(mcp, token) if mcp is not None else None

    @contextlib.asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        if mounted is None:
            yield
            return
        async with mounted[1]():
            yield

    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))

    @app.middleware("http")
    async def no_browsers(request: Request, call_next: Any) -> Response:
        if request.headers.get("origin") is not None:
            return _not_allowed()
        response: Response = await call_next(request)
        response.headers.update(HEADERS)
        return response

    @app.get("/health", include_in_schema=False)
    async def health() -> JSONResponse:
        return JSONResponse({"name": "jarvis", "version": __version__})

    if page_origins and port is not None and ui_token is not None:
        page_port, page_token = port, ui_token

        @app.get("/", include_in_schema=False)
        async def chat(request: Request) -> Response:
            """The chat window. Only a navigation from nowhere or this page itself gets it."""
            if request.headers.get("sec-fetch-site", "none") not in ("none", "same-origin"):
                return _not_allowed()  # another site, even another port on this computer
            html, policy = ui.page(page_port, page_token)
            return HTMLResponse(
                html,
                headers={"Content-Security-Policy": policy, "X-Frame-Options": "DENY"},
            )

    @app.post("/bridge", include_in_schema=False)
    async def bridge(request: Request) -> JSONResponse:
        """Claude Code's hook asks you something (ADR-051)."""
        sent = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not _token_ok(sent, bridge_token):
            return _not_allowed()
        if runtime.bridge is None:
            return JSONResponse({"error": "the bridge is off"}, status_code=503)
        try:
            ask = BridgeRequest.parse(await request.json())
        except (ValueError, json.JSONDecodeError) as exc:
            return JSONResponse({"error": str(exc)}, status_code=400)
        return JSONResponse(await runtime.bridge.handle(ask))

    @app.websocket("/ws")
    async def socket(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        sent = ws.query_params.get("token")
        if origin is None:
            allowed = _token_ok(sent, token)  # a program on this computer
        else:
            allowed = origin in page_origins and _token_ok(sent, ui_token)  # the chat page
            if not allowed:
                log.warning("Refused a WebSocket connection from origin %r", origin)
        if not allowed:
            await ws.close(code=POLICY_VIOLATION)  # before accepting: the browser gets a 403
            return
        await ws.accept()
        await converse(runtime, ws)

    if mounted is not None:
        app.mount("/mcp", mounted[0])
    return app


async def converse(runtime: Runtime, ws: WebSocket) -> None:
    """One client's connection: send hello, stream events out, handle requests coming in."""
    client = Client(ws.send_text)
    runtime.hub.connect(client)
    client.send(runtime.hello())
    pump = asyncio.create_task(client.pump(), name="ws-pump")
    log.info("API client connected (%d open)", runtime.hub.client_count)
    try:
        while not client.dropped:
            raw = await ws.receive_text()
            try:
                message = json.loads(raw)
            except json.JSONDecodeError:
                client.send({"type": "error", "message": "Messages must be JSON."})
                continue
            if isinstance(message, dict):
                await runtime.handle(client, message)
    except WebSocketDisconnect:
        pass
    finally:
        runtime.hub.disconnect(client)
        pump.cancel()
        await asyncio.gather(pump, return_exceptions=True)
        log.info("API client disconnected (%d open)", runtime.hub.client_count)
