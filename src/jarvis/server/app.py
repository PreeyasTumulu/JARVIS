"""The local API: JSON over HTTP and one WebSocket, for programs on this computer only.

There is no page any more (ADR-081); a new UI will connect here. What keeps other programs and
websites out:

1. The server listens on 127.0.0.1 only (set in serve.py, not configurable).
2. The Host header must name this computer, which defeats DNS rebinding.
3. Browsers always send an Origin header with a WebSocket or a cross-site request and cannot
   leave it out, so any request that carries one is refused. No website can reach the API.
4. The WebSocket and the bridge need the per-launch token, which `jarvis serve` writes to the
   data folder (only this Windows account can read it).

`GET /health` says only that Jarvis is up and which version, so a client can find it.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Sequence
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from starlette.middleware.trustedhost import TrustedHostMiddleware

from jarvis import __version__
from jarvis.bridge.service import BridgeRequest
from jarvis.server.hub import Client
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
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
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
        if origin is not None:
            log.warning("Refused a WebSocket connection from origin %r", origin)
            await ws.close(code=POLICY_VIOLATION)  # before accepting: the browser gets a 403
            return
        if not _token_ok(ws.query_params.get("token"), token):
            await ws.close(code=POLICY_VIOLATION)
            return
        await ws.accept()
        await converse(runtime, ws)

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
