"""Send the model only the tool groups a request is about.

An 8B model picks the right tool far less often when it sees every tool at once (see
docs/benchmarks). Cheap keyword matching on the request selects one or more groups; a request
that matches nothing gets every tool, so routing can narrow the choice but never hide a tool
the model might need for an unusual request. The executor still accepts any registered tool.
"""

from __future__ import annotations

import re

from jarvis.tools.registry import Registry, Tool

ALWAYS = ("ask_user", "speak")

GROUPS: dict[str, tuple[tuple[str, ...], re.Pattern[str]]] = {
    "apps": (
        ("open_app", "focus_app", "close_app"),
        re.compile(
            r"\b(open|launch|start|run|close|quit|exit|switch|focus|bring up|go to|app|apps|"
            r"application|window)\b"
        ),
    ),
    "files": (
        ("find_file", "open_file", "read_file", "get_selected_file", "vscode_open"),
        re.compile(
            r"\b(file|files|document|documents|doc|docs|folder|pdf|resume|cv|readme|notes?|"
            r"report|invoice|this|selected|read|project|downloads|desktop|vs ?code|code)\b"
            r"|\.\w{2,4}\b"
        ),
    ),
    "docker": (
        ("docker_list", "docker_logs", "docker_start", "docker_stop", "open_app"),
        re.compile(r"\b(docker|containers?|compose|postgres|redis|mongo|mysql|nginx|images?)\b"),
    ),
    "web": (
        ("web_search", "open_url"),
        re.compile(
            r"\b(search|look up|lookup|google|news|who|what|when|where|why|how|latest|website|"
            r"site|weather|price|score|wiki\w*|browser)\b|https?://|\.(com|org|net|io|dev|in)\b"
        ),
    ),
}


def select_tools(text: str, registry: Registry) -> list[Tool]:
    lowered = text.casefold()
    wanted: set[str] = set()
    for names, pattern in GROUPS.values():
        if pattern.search(lowered):
            wanted.update(names)
    if not wanted:
        return list(registry)
    wanted.update(ALWAYS)
    return [tool for tool in registry if tool.name in wanted]
