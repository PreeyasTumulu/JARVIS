"""Jarvis's own tools for other MCP clients (ADR-085).

Claude Code, Claude Desktop, or any MCP client runs `jarvis mcp serve` (server/mcp_stdio.py),
which forwards to the running `jarvis serve` here, at `/mcp/` on the local API, with the API's
token. This module decides what is offered and runs each call:

- Only public tools listed in `[mcp_server] tools` are offered. A private tool (messages,
  files, mail, notifications, memory, the screen) is never offered, whatever the config says:
  an MCP client usually sends tool results to a cloud model, and nothing private may reach one.
- Every call goes through `Agent.run_call`: the same argument check, policy gate, one-time
  clearance, and audit as a call the model makes, one at a time with voice and chat turns.
- A call that needs a yes is asked on Jarvis's own channels (voice, the terminal, API clients),
  naming the client. The client's own approval never counts.
- The audit log records the call with `handled_by = "mcp:<client>"`.
"""

from __future__ import annotations

import contextlib
import json
import logging
import re
import uuid
from collections.abc import AsyncIterator, Sequence
from typing import TYPE_CHECKING, Any

from jarvis.core.channel import ConfirmationRequest, UserChannel
from jarvis.core.executor import CallOutcome, Decision
from jarvis.core.prompts import truncate, wrap_untrusted
from jarvis.llm.types import ToolCall
from jarvis.tools.base import Sensitivity

if TYPE_CHECKING:
    from jarvis.core.agent import Agent
    from jarvis.tools.registry import Registry, Tool

log = logging.getLogger(__name__)

CLIENT_HEADER = "x-jarvis-client"  # the client's name, as the stdio command heard it
_CLIENT_NAME = re.compile(r"[^A-Za-z0-9 ._-]")
MAX_RESULT_CHARS = 8000
_warned: set[str] = set()  # each refused name is logged once, not on every call


def _warn_once(name: str, message: str) -> None:
    if name not in _warned:
        _warned.add(name)
        log.warning(message, name)


def client_label(raw: str | None) -> str:
    """A short, printable client name for questions and the audit log."""
    name = _CLIENT_NAME.sub("", (raw or "").strip())[:40].strip()
    return name or "An MCP client"


def offered_tools(registry: Registry, wanted: Sequence[str]) -> list[Tool]:
    """The listed tools that may be offered: they exist and they are public."""
    found: list[Tool] = []
    for name in dict.fromkeys(wanted):
        tool = registry.get(name)
        if tool is None:
            _warn_once(name, "[mcp_server] lists %s, which is not a Jarvis tool")
        elif tool.sensitivity is not Sensitivity.PUBLIC:
            _warn_once(name, "[mcp_server] lists %s, a private tool; it is never offered")
        else:
            found.append(tool)
    return found


def tool_listing(tool: Tool) -> dict[str, Any]:
    """The MCP description of one tool: name, description, and its JSON schema."""
    function = tool.schema()["function"]
    return {
        "name": function["name"],
        "description": function["description"],
        "input_schema": function["parameters"],
    }


class ClientChannel:
    """Jarvis's own channels, with questions from `ask_user` naming the client. Confirmations
    name it already (`ToolContext.requester`: "Claude Code wants to: Open Paint")."""

    def __init__(self, inner: UserChannel, client: str) -> None:
        self._inner = inner
        self._client = client

    @property
    def name(self) -> str:
        return self._inner.name

    async def confirm(self, request: ConfirmationRequest) -> bool:
        return await self._inner.confirm(request)

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        return await self._inner.ask(f"{self._client} asks: {question}", options)


class McpGateway:
    """What the `/mcp/` endpoint offers and how it runs a call."""

    def __init__(self, agent: Agent) -> None:
        self._agent = agent

    def tools(self) -> list[Tool]:
        cfg = self._agent.settings.mcp_server
        if not cfg.enabled:
            return []
        return offered_tools(self._agent.registry, cfg.tools)

    def listing(self) -> list[dict[str, Any]]:
        return [tool_listing(tool) for tool in self.tools()]

    async def call(
        self, name: str, arguments: dict[str, Any] | None, client: str | None
    ) -> tuple[str, bool]:
        """Run one call; (text for the client, whether it failed)."""
        label = client_label(client)
        if name not in {tool.name for tool in self.tools()}:
            log.warning("%s asked for %s, which is not offered", label, name)
            return f"Jarvis does not offer a tool called {name}.", True
        call = ToolCall(
            id=f"mcp_{uuid.uuid4().hex[:12]}",
            name=name,
            arguments=json.dumps(arguments or {}, ensure_ascii=False),
        )
        channel = ClientChannel(self._agent.channel, label)
        outcome = await self._agent.run_call(call, channel, f"mcp:{label}", label)
        log.info("%s ran %s: %s", label, name, outcome.decision)
        return client_content(outcome), not outcome.result.ok


_REFUSED = {
    Decision.DENIED: "The user said no in Jarvis, so it was not done. Do not ask again.",
    Decision.TIMEOUT: "The user did not answer in Jarvis in time, so it was not done.",
}


def client_content(outcome: CallOutcome) -> str:
    """The result for an outside client: the data and the one-line summary, without the
    reply hints written for Jarvis's own small model. Outside content stays marked as data."""
    result = outcome.result
    payload: dict[str, Any] = {"ok": result.ok}
    if result.ok:
        if result.speech:
            payload["summary"] = result.speech
        payload["data"] = result.data
    else:
        payload["error"] = _REFUSED.get(outcome.decision) or result.error
    text = truncate(json.dumps(payload, ensure_ascii=False, default=str), MAX_RESULT_CHARS)
    if outcome.tool is not None and outcome.tool.untrusted and result.ok:
        text = wrap_untrusted(outcome.call.name, text)
    return text


def mcp_app(gateway: McpGateway, token: str) -> tuple[Any, Any]:
    """The ASGI app for `/mcp/` and a lifespan to run it in (the SDK's session manager)."""
    from mcp import types
    from mcp.server.lowlevel import Server
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager

    from jarvis import __version__

    async def list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
        return types.ListToolsResult(tools=[types.Tool(**item) for item in gateway.listing()])

    async def call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
        request = getattr(ctx, "request", None)
        headers = getattr(request, "headers", None) or {}
        text, failed = await gateway.call(params.name, params.arguments, headers.get(CLIENT_HEADER))
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
    manager = StreamableHTTPSessionManager(server, stateless=True, json_response=True)

    async def app(scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope["type"] == "http" and not _authorized(scope, token):
            await _refuse(send)
            return
        await manager.handle_request(scope, receive, send)

    @contextlib.asynccontextmanager
    async def lifespan() -> AsyncIterator[None]:
        async with manager.run():
            yield

    return app, lifespan


def _authorized(scope: dict[str, Any], token: str) -> bool:
    import secrets

    for key, value in scope.get("headers", []):
        if key == b"authorization":
            sent = value.decode("latin-1").removeprefix("Bearer ").strip()
            return secrets.compare_digest(sent, token)
    return False


async def _refuse(send: Any) -> None:
    body = b'{"error": "not allowed"}'
    await send(
        {
            "type": "http.response.start",
            "status": 403,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": body})
