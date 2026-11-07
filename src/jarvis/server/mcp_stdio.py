"""`jarvis mcp serve`: Jarvis's tools for an MCP client, over stdio (ADR-085).

An MCP client (Claude Code, Claude Desktop) starts this command and talks MCP on its stdin and
stdout. It lists the tools `[mcp_server]` offers (server/mcp_server.py decides which), and
forwards every call to the running `jarvis serve` at `/mcp/` with the token from the data
folder, so the call meets the policy gate, the audit log, and a confirmation asked on Jarvis's
own voice and terminal. Nothing runs in this process. When Jarvis is not running, a call says
so instead of failing silently.

stdout carries the protocol, so this command never prints: its log goes to
logs/mcp-serve.log.
"""

from __future__ import annotations

import contextlib
import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

from jarvis.bridge.service import bridge_file
from jarvis.config import Settings
from jarvis.server.mcp_server import CLIENT_HEADER, offered_tools, tool_listing

log = logging.getLogger(__name__)

NOT_RUNNING = (
    "Jarvis is not running, so this tool cannot run. Start it with `uv run jarvis serve` "
    "(or turn on start at login) and try again."
)
SLACK_S = 30  # on top of the confirmation time limit and the tool's own


def _log_to_file(data_dir: Path) -> None:
    log_dir = data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_dir / "mcp-serve.log", maxBytes=1_000_000, backupCount=1, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(logging.INFO)


def address(data_dir: Path) -> tuple[int, str] | None:
    """The running Jarvis's port and token, or None when it is not running."""
    try:
        found = json.loads(bridge_file(data_dir).read_text("utf-8"))
        return int(found["port"]), str(found["token"])
    except (OSError, ValueError, KeyError, TypeError):
        return None


def listing(settings: Settings) -> list[dict[str, Any]]:
    """What this command offers: decided here too, so a client sees the tools before Jarvis
    starts. The running Jarvis checks again on every call."""
    from jarvis.tools.catalog import build_registry

    if not settings.mcp_server.enabled:
        return []
    return [tool_listing(t) for t in offered_tools(build_registry(), settings.mcp_server.tools)]


async def forward(
    settings: Settings, name: str, arguments: dict[str, Any] | None, client: str
) -> tuple[str, bool]:
    """Run one call in the running Jarvis; (text, failed)."""
    import httpx2
    from mcp import ClientSession
    from mcp.client.streamable_http import streamable_http_client

    found = address(settings.data_dir)
    if found is None:
        return NOT_RUNNING, True
    port, token = found
    limit = settings.safety.confirm_timeout_s + settings.agent.tool_timeout_s + SLACK_S
    headers = {"Authorization": f"Bearer {token}", CLIENT_HEADER: client}
    try:
        async with (
            httpx2.AsyncClient(headers=headers, timeout=limit) as http,
            streamable_http_client(f"http://127.0.0.1:{port}/mcp/", http_client=http) as streams,
            ClientSession(streams[0], streams[1]) as session,
        ):
            await session.initialize()
            result = await session.call_tool(name, arguments or {})
    except Exception as exc:
        log.warning("Forwarding %s failed: %s", name, exc)
        return NOT_RUNNING, True
    text = "\n".join(getattr(part, "text", "") for part in result.content).strip()
    return text, bool(result.is_error)


def client_name(ctx: Any) -> str:
    """The client's own name from the MCP handshake, for questions and the audit log."""
    params = getattr(getattr(ctx, "session", None), "client_params", None)
    info = getattr(params, "client_info", None)
    return str(getattr(info, "title", None) or getattr(info, "name", None) or "")


async def serve(settings: Settings) -> None:
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server

    from jarvis import __version__

    tools = listing(settings)
    log.info("jarvis mcp serve: offering %s", ", ".join(t["name"] for t in tools) or "nothing")

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(**item) for item in tools])

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        text, failed = await forward(settings, params.name, params.arguments, client_name(ctx))
        return types.CallToolResult(
            content=[types.TextContent(type="text", text=text)], is_error=failed
        )

    server: Any = Server(
        "jarvis",
        version=__version__,
        instructions="Tools of Jarvis, a local assistant on this laptop. Calls that need the "
        "user's yes are asked on Jarvis's own voice and terminal and may take up to a minute.",
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    async with stdio_server() as (read, write):
        await server.run(read, write, server.create_initialization_options())


def run_mcp_stdio(settings: Settings) -> int:
    import anyio

    _log_to_file(settings.data_dir)
    with contextlib.suppress(KeyboardInterrupt):
        anyio.run(serve, settings)
    return 0
