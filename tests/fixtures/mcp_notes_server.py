"""A tiny MCP server for tests, run over stdio: notes in memory.

    python tests/fixtures/mcp_notes_server.py

Tools: list_notes (read-only), add_note (writes), delete_notes (destructive), fail (an error),
and secret_tool (never listed in config, so Jarvis must not expose it).
"""

from __future__ import annotations

from mcp.server.mcpserver import MCPServer
from mcp.types import ToolAnnotations

server = MCPServer("notes")
NOTES: list[str] = ["buy milk"]


@server.tool(annotations=ToolAnnotations(read_only_hint=True, open_world_hint=False))
def list_notes(contains: str = "") -> str:
    """List the saved notes, optionally only those containing some text."""
    found = [note for note in NOTES if contains.casefold() in note.casefold()]
    return "\n".join(found) or "no notes"


@server.tool(annotations=ToolAnnotations(read_only_hint=False, destructive_hint=False))
def add_note(text: str) -> str:
    """Save a note."""
    NOTES.append(text)
    return f"saved ({len(NOTES)} notes)"


@server.tool(annotations=ToolAnnotations(destructive_hint=True))
def delete_notes() -> str:
    """Delete every note."""
    NOTES.clear()
    return "deleted"


@server.tool()
def fail() -> str:
    """Always fails."""
    raise ValueError("the notes server broke on purpose")


@server.tool()
def secret_tool() -> str:
    """Not listed in Jarvis's config."""
    return "you should never see this"


if __name__ == "__main__":
    server.run("stdio")
