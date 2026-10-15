"""The FastAPI app: a static page and one WebSocket, locked to this computer and this launch.

Browsers do not apply CORS to WebSockets, so any website you visit could try to talk to
`ws://127.0.0.1`. Four checks keep it out (ADR-011, ADR-035):

1. The server listens on 127.0.0.1 only (set in serve.py, not configurable).
2. The Host header must name this computer, which defeats DNS rebinding.
3. The WebSocket's Origin must be this page, and its URL must carry the random per-launch token.
4. The page cannot be framed by another site (CSP frame-ancestors), so a hidden frame cannot
   trick you into clicking Confirm.
"""

from __future__ import annotations

import asyncio
import json
import logging
import secrets
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from jarvis.server.hub import Client
from jarvis.server.runtime import Runtime

log = logging.getLogger(__name__)

STATIC = Path(__file__).parent / "static"
LOCAL_HOSTS = ("127.0.0.1", "localhost")
POLICY_VIOLATION = 1008


def security_headers(port: int, hosts: Sequence[str]) -> dict[str, str]:
    sockets = " ".join(f"ws://{host}:{port}" for host in hosts)
    return {
        "Content-Security-Policy": (
            "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
            f"connect-src 'self' {sockets}; frame-ancestors 'none'; base-uri 'none'; "
            "form-action 'none'"
        ),
        "X-Frame-Options": "DENY",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",  # the token is in the page URL
        "Cache-Control": "no-store",
    }


def create_server(
    runtime: Runtime, *, token: str, port: int, hosts: Sequence[str] = LOCAL_HOSTS
) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(hosts))
    origins = {f"http://{host}:{port}" for host in hosts}
    headers = security_headers(port, hosts)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(STATIC / "index.html", headers=headers)

    app.mount("/static", StaticFiles(directory=STATIC), name="static")

    @app.middleware("http")
    async def revalidate(request: Request, call_next: Any) -> Response:
        # Tiny local files: always check the ETag, so an upgraded Jarvis never runs an old script.
        response: Response = await call_next(request)
        response.headers.setdefault("Cache-Control", "no-cache")
        return response

    @app.websocket("/ws")
    async def socket(ws: WebSocket) -> None:
        origin = ws.headers.get("origin")
        if origin not in origins:
            log.warning("Refused a WebSocket connection from origin %r", origin)
            await ws.close(code=POLICY_VIOLATION)  # before accepting: the browser gets a 403
            return
        if not secrets.compare_digest(ws.query_params.get("token", ""), token):
            # Our own page with an old token (Jarvis restarted). Accept only to say why, so the
            # page can tell you to open the new link; nothing else is sent.
            await ws.accept()
            await ws.close(code=POLICY_VIOLATION, reason="invalid token")
            return
        await ws.accept()
        await converse(runtime, ws)

    return app


async def converse(runtime: Runtime, ws: WebSocket) -> None:
    """One tab's connection: send hello, stream events out, handle requests coming in."""
    client = Client(ws.send_text)
    runtime.hub.connect(client)
    client.send(runtime.hello())
    pump = asyncio.create_task(client.pump(), name="ws-pump")
    log.info("Browser tab connected (%d open)", runtime.hub.client_count)
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
        log.info("Browser tab disconnected (%d open)", runtime.hub.client_count)
