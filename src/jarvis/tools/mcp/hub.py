"""MCP servers as Jarvis tools (ADR-059).

Each server in `[mcp.servers.<name>]` is started (a command over stdio, such as GitHub's server
in Docker) or reached (a URL over Streamable HTTP) on first use, and only the tools its config
lists become Jarvis tools, named `<server>_<tool>`. Every one goes through the same policy gate
as a built-in tool: the floor is `confirm`, a tool the server marks read-only runs without
asking only on a server you marked `trusted`, config can only make a tool stricter, results
are private and untrusted, and a tool that reaches the outside world counts as egress.

The SDK's transports run inside anyio task groups, which must be entered and left in the same
task, so each server lives in its own long-running task and calls reach its session from the
agent's task.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.config import McpServerSettings, McpSettings

log = logging.getLogger(__name__)

_VAR = re.compile(r"\$\{?([A-Z][A-Z0-9_]*)\}?")


class McpError(Exception):
    """Something to tell the user about an MCP server."""


@dataclass(frozen=True)
class RemoteTool:
    server: str
    name: str
    description: str
    input_schema: dict[str, Any]
    read_only: bool
    destructive: bool
    open_world: bool


def expand(value: str, environ: dict[str, str] | os._Environ[str] = os.environ) -> str:
    """$NAME and ${NAME} from the environment (secrets live in .env, never in config)."""
    return _VAR.sub(lambda m: environ.get(m.group(1), ""), value)


def missing_vars(server: McpServerSettings, environ: Any = os.environ) -> list[str]:
    texts = [
        server.url,
        server.command,
        *server.args,
        *server.env.values(),
        *server.headers.values(),
    ]
    names = {m.group(1) for text in texts for m in _VAR.finditer(text)}
    return sorted(name for name in names if not environ.get(name))


def result_text(result: Any) -> tuple[Any, bool]:
    """(data for the model, is_error) from a CallToolResult."""
    parts: list[str] = []
    for block in result.content or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(text)
        elif getattr(block, "type", "") == "image":
            parts.append("[an image]")
        elif getattr(block, "type", "") == "resource":
            resource = getattr(block, "resource", None)
            parts.append(getattr(resource, "text", None) or "[a file]")
    structured = getattr(result, "structured_content", None)
    if isinstance(structured, dict) and set(structured) == {"result"}:
        structured = structured["result"]  # a plain return value, wrapped by the SDK
    data: Any = structured if structured not in (None, {}, "") else "\n".join(parts)
    return data, bool(getattr(result, "is_error", False))


@dataclass
class _Server:
    name: str
    settings: McpServerSettings
    task: asyncio.Task[None] | None = None
    session: Any = None
    tools: list[RemoteTool] = field(default_factory=list)
    error: str = ""
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    stop: asyncio.Event = field(default_factory=asyncio.Event)


class McpHub:
    def __init__(
        self,
        settings: McpSettings,
        log_dir: Path | None = None,
        connect: Callable[[str, McpServerSettings], Any] | None = None,
    ) -> None:
        self._cfg = settings
        self._log_dir = log_dir
        self._connect = connect or self._transport
        self._servers: dict[str, _Server] = {}
        self._started = False
        self._lock = asyncio.Lock()

    @property
    def servers(self) -> dict[str, _Server]:
        return self._servers

    def configured(self) -> dict[str, McpServerSettings]:
        if not self._cfg.enabled:
            return {}
        return {name: s for name, s in self._cfg.servers.items() if s.enabled}

    async def start(self) -> list[RemoteTool]:
        """Connect to every enabled server whose secrets are set; return the listed tools.

        A server that fails is logged and skipped: the rest of Jarvis keeps working.
        """
        async with self._lock:
            if not self._started:
                self._started = True
                for name, server in self.configured().items():
                    missing = missing_vars(server)
                    if missing:
                        log.info(
                            "MCP server %s skipped: %s not set in .env", name, ", ".join(missing)
                        )
                        continue
                    entry = _Server(name, server)
                    entry.task = asyncio.create_task(self._run(entry), name=f"mcp-{name}")
                    self._servers[name] = entry
            waits = [s.ready.wait() for s in self._servers.values()]
            if waits:
                with contextlib.suppress(TimeoutError):
                    async with asyncio.timeout(self._cfg.connect_timeout_s):
                        await asyncio.gather(*waits)
        found = []
        for entry in self._servers.values():
            if entry.session is None and not entry.error:
                entry.error = f"did not answer within {self._cfg.connect_timeout_s:.0f}s"
            if entry.error:
                log.warning("MCP server %s unavailable: %s", entry.name, entry.error)
            found += entry.tools
        return found

    async def _run(self, entry: _Server) -> None:
        from mcp import ClientSession

        try:
            async with self._connect(entry.name, entry.settings) as streams:
                read, write = streams[0], streams[1]
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    entry.tools = self._pick(entry, listed.tools)
                    entry.session = session
                    entry.ready.set()
                    log.info(
                        "MCP server %s ready: %d of %d tools exposed",
                        entry.name,
                        len(entry.tools),
                        len(listed.tools),
                    )
                    await entry.stop.wait()
        except Exception as exc:  # a broken server must not take Jarvis down
            entry.error = _short(exc)
            log.warning("MCP server %s failed: %s", entry.name, entry.error)
        finally:
            entry.session = None
            entry.ready.set()

    def _pick(self, entry: _Server, offered: list[Any]) -> list[RemoteTool]:
        wanted = entry.settings.tools
        if wanted == ["*"]:  # every tool (jarvis mcp tools, or a deliberate choice)
            wanted = [tool.name for tool in offered]
        by_name = {tool.name: tool for tool in offered}
        for name in wanted:
            if name not in by_name:
                log.warning("MCP server %s has no tool called %s", entry.name, name)
        picked = []
        for name in wanted:
            tool = by_name.get(name)
            if tool is None:
                continue
            notes = tool.annotations
            picked.append(
                RemoteTool(
                    server=entry.name,
                    name=tool.name,
                    description=(tool.description or tool.title or tool.name).strip(),
                    input_schema=dict(tool.input_schema or {"type": "object", "properties": {}}),
                    read_only=bool(notes and notes.read_only_hint),
                    destructive=bool(notes is None or notes.destructive_hint is not False),
                    open_world=bool(notes is None or notes.open_world_hint is not False),
                )
            )
        return picked

    async def offered(self, name: str) -> list[RemoteTool]:
        """Every tool a server offers, listed or not (for `jarvis mcp tools`)."""
        server = self.configured().get(name)
        if server is None:
            raise McpError(f"There is no enabled MCP server called {name}.")
        missing = missing_vars(server)
        if missing:
            raise McpError(f"Set {', '.join(missing)} in .env first.")
        everything = server.model_copy(update={"tools": ["*"]})
        probe = McpHub(
            self._cfg.model_copy(update={"enabled": True, "servers": {name: everything}}),
            self._log_dir,
            self._connect,
        )
        try:
            found = await probe.start()
            entry = probe.servers.get(name)
            if not found and entry is not None and entry.error:
                raise McpError(f"{name} failed: {entry.error}")
            return found
        finally:
            await probe.aclose()

    async def call(self, server: str, tool: str, arguments: dict[str, Any]) -> tuple[Any, bool]:
        entry = self._servers.get(server)
        if entry is None or entry.session is None:
            reason = entry.error if entry is not None and entry.error else "it is not running"
            raise McpError(f"The {server} server is not available ({reason}).")
        try:
            async with asyncio.timeout(self._cfg.call_timeout_s):
                result = await entry.session.call_tool(tool, arguments)
        except TimeoutError as exc:
            raise McpError(f"{server} took longer than {self._cfg.call_timeout_s:.0f}s.") from exc
        except Exception as exc:
            raise McpError(f"{server} failed: {_short(exc)}") from exc
        return result_text(result)

    async def aclose(self) -> None:
        for entry in self._servers.values():
            entry.stop.set()
        tasks = [e.task for e in self._servers.values() if e.task is not None]
        if tasks:
            with contextlib.suppress(TimeoutError):
                async with asyncio.timeout(10):
                    await asyncio.gather(*tasks, return_exceptions=True)
        self._servers.clear()
        self._started = False

    @contextlib.asynccontextmanager
    async def _transport(self, name: str, server: McpServerSettings) -> Any:
        if server.url:
            import httpx2
            from mcp.client.streamable_http import streamable_http_client

            headers = {key: expand(value) for key, value in server.headers.items()}
            async with (
                httpx2.AsyncClient(headers=headers, timeout=self._cfg.call_timeout_s) as http,
                streamable_http_client(expand(server.url), http_client=http) as streams,
            ):
                yield streams
            return
        from mcp import StdioServerParameters
        from mcp.client.stdio import stdio_client

        env = {**os.environ, **{key: expand(value) for key, value in server.env.items()}}
        params = StdioServerParameters(
            command=expand(server.command),
            args=[expand(arg) for arg in server.args],
            env=env,
            cwd=server.cwd or None,
        )
        # Under pythonw there is no stderr, so the server's own log goes to a file.
        errlog_path = (self._log_dir or Path.cwd()) / f"mcp-{name}.log"
        errlog_path.parent.mkdir(parents=True, exist_ok=True)
        with errlog_path.open("a", encoding="utf-8") as errlog:
            async with stdio_client(params, errlog=errlog) as streams:
                yield streams


def _short(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        return _short(exc.exceptions[0])
    text = str(exc).strip() or type(exc).__name__
    return text if len(text) < 300 else text[:297] + "..."
