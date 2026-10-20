"""Turn the MCP tools a server's config lists into Jarvis tools (ADR-059).

The risk floor is `confirm`. A tool runs without asking only when the server marks it read-only
and you marked the server `trusted`; `[mcp.servers.<name>.risk]` and `safety.tool_risk_overrides`
can raise any tool, never lower it. Results are private (unless the server is labelled public)
and always untrusted. A tool that reaches the outside world (open-world, which is MCP's default)
is egress, so it asks once private and outside content are both in the conversation.
"""

from __future__ import annotations

import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from jarvis.config import McpServerSettings
from jarvis.tools.base import Prepared, Risk, ToolContext, ToolError, ToolResult
from jarvis.tools.mcp.hub import McpError, McpHub, RemoteTool
from jarvis.tools.registry import Tool

MAX_DESCRIPTION = 300
MAX_PARAM_TEXT = 100
_TYPES: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list[Any],
    "object": dict[str, Any],
}


def tool_name(server: str, tool: str) -> str:
    """'github' and 'list_issues' to 'github_list_issues' (letters, digits, _ and -, max 64)."""
    name = re.sub(r"[^A-Za-z0-9_-]", "_", f"{server}_{tool}")
    return name[:64]


def risk_for(remote: RemoteTool, server: McpServerSettings) -> Risk:
    base = Risk.SAFE if server.trusted and remote.read_only else Risk.CONFIRM
    return Risk.highest(base, server.risk.get(remote.name, Risk.SAFE))


def args_model(name: str, schema: dict[str, Any]) -> type[BaseModel]:
    """A pydantic model for the top level of a JSON schema. Deeper checks are the server's."""
    required = set(schema.get("required") or [])
    fields: dict[str, Any] = {}
    for key, spec in (schema.get("properties") or {}).items():
        kind = spec.get("type") if isinstance(spec, dict) else None
        python = _TYPES.get(kind, Any) if isinstance(kind, str) else Any
        if key in required:
            fields[key] = (python, Field(...))
        else:
            fields[key] = (python | None, Field(None))
    model: type[BaseModel] = create_model(
        f"{name}_args", __config__=ConfigDict(extra="ignore"), **fields
    )
    return model


def _clean(node: Any, depth: int = 0) -> Any:
    """Drop JSON schema keys that cost tokens and add nothing for the model, cut long
    descriptions, and collapse objects nested inside arrays (GitHub's issue_write alone was
    3,700 characters, and every character is prompt the 8B model has to read)."""
    if isinstance(node, list):
        return [_clean(item, depth) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key == "properties" and isinstance(value, dict):  # parameter names stay, even "title"
            cleaned[key] = {name: _clean(spec, depth + 1) for name, spec in value.items()}
            continue
        if key in ("$schema", "title", "additionalProperties", "$id", "examples", "default"):
            continue
        if key.startswith("x-"):
            continue
        if key == "description" and isinstance(value, str) and len(value) > MAX_PARAM_TEXT:
            value = value[: MAX_PARAM_TEXT - 3].rstrip() + "..."
        if key == "items" and isinstance(value, dict) and value.get("type") == "object":
            value = {"type": "object"}  # its fields are the server's business
        cleaned[key] = _clean(value, depth + 1)
    return cleaned


def compact_schema(schema: dict[str, Any], keep: list[str] | None) -> dict[str, Any]:
    """The schema the model sees: only the parameters config lists (plus required ones)."""
    trimmed = dict(schema)
    properties = dict(schema.get("properties") or {})
    required = [name for name in schema.get("required") or [] if name in properties]
    if keep is not None:
        wanted = set(keep) | set(required)
        properties = {name: spec for name, spec in properties.items() if name in wanted}
    trimmed["properties"] = properties
    if required:
        trimmed["required"] = required
    result: dict[str, Any] = _clean(trimmed)
    result.setdefault("type", "object")
    return result


def _spoken_args(args: dict[str, Any]) -> str:
    parts = []
    for key, value in args.items():
        text = value if isinstance(value, str) else repr(value)
        text = text if len(text) <= 200 else text[:197] + "..."
        parts.append(f"{key.replace('_', ' ')}: {text}")
    return "; ".join(parts)


def build_tool(hub: McpHub, remote: RemoteTool, server: McpServerSettings) -> Tool:
    label = server.label or remote.server
    name = tool_name(remote.server, remote.name)
    risk = risk_for(remote, server)

    async def run(ctx: ToolContext, **args: Any) -> ToolResult:
        given = {key: value for key, value in args.items() if value is not None}
        try:
            data, failed = await hub.call(remote.server, remote.name, given)
        except McpError as exc:
            raise ToolError(str(exc)) from exc
        if failed:
            raise ToolError(f"{label} said: {str(data)[:500]}")
        return ToolResult.success(data={"server": label, "result": data})

    async def prepare(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
        given = {key: value for key, value in args.items() if value is not None}
        what = _spoken_args(given)
        summary = f"{label}: {remote.name.replace('_', ' ')}" + (f" ({what})" if what else "")
        return Prepared(
            args=args,
            summary=summary,
            risk=risk,
            reason=None if risk is Risk.SAFE else f"{label} tools ask first unless read-only",
        )

    description = remote.description
    if len(description) > MAX_DESCRIPTION:
        description = description[: MAX_DESCRIPTION - 3].rstrip() + "..."
    words = [remote.server, label, *server.keywords]
    route = re.compile(r"\b(" + "|".join(re.escape(w.casefold()) for w in words if w) + r")\b")
    parameters = compact_schema(remote.input_schema, server.params.get(remote.name))
    return Tool(
        name=name,
        description=f"[{label}] {description}",
        risk=risk,
        sensitivity=server.sensitivity,
        untrusted=True,
        timeout_s=None,  # the hub applies mcp.call_timeout_s
        args_model=args_model(name, parameters),
        fn=run,
        prepare_fn=prepare,
        egress=remote.open_world,
        parameters=parameters,
        route=route,
    )


def register_all(
    registry: Any, hub: McpHub, remotes: list[RemoteTool], servers: dict[str, McpServerSettings]
) -> list[str]:
    """Register the listed MCP tools; returns their Jarvis names. Names already taken are
    skipped (a built-in tool always wins)."""
    added = []
    for remote in remotes:
        item = build_tool(hub, remote, servers[remote.server])
        if registry.get(item.name) is None:
            registry.register(item)
            added.append(item.name)
    return added
