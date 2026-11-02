"""`jarvis claude-hook`: what Claude Code runs for its hooks, and installing those hooks.

Claude Code sends the hook event as JSON on stdin (code.claude.com/docs/en/hooks):

- PreToolUse for AskUserQuestion: Jarvis asks you, and the answer goes back as
  `updatedInput.answers` with `permissionDecision: "allow"`, which answers the question.
- PermissionRequest: a clear spoken yes allows the tool, no denies it.
- Notification: "Claude is waiting for you" and "Claude finished" are said aloud.

Anything that goes wrong (Jarvis not running, no answer, a timeout) prints nothing, which
leaves Claude Code to ask you itself as usual. The hook never blocks Claude.
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any

import httpx

from jarvis.bridge.service import bridge_file

log = logging.getLogger(__name__)

HOOK_TIMEOUT_S = 600  # Claude Code's own limit for a command hook
MARK = "claude-hook"  # how install and uninstall recognize Jarvis's entries
NOTICES = {
    "idle_prompt": "Claude is waiting for you{where}.",
    "agent_completed": "Claude finished{where}.",
    "elicitation_dialog": "Claude needs your input{where}.",
}
SKIP_PERMISSIONS = {"AskUserQuestion", "ExitPlanMode"}  # a plan is read, not approved by ear


def permission_text(tool: str, tool_input: dict[str, Any]) -> str:
    """ "run npm test", "edit app.py": short enough to say aloud."""

    def short(value: Any, limit: int = 160) -> str:
        text = " ".join(str(value or "").split())
        return text if len(text) <= limit else text[: limit - 3] + "..."

    if tool == "Bash":
        return f"run {short(tool_input.get('command'))}"
    if tool in ("Edit", "MultiEdit", "Write", "NotebookEdit"):
        verb = "write" if tool == "Write" else "edit"
        path = tool_input.get("file_path") or tool_input.get("notebook_path")
        return f"{verb} {Path(str(path or 'a file')).name}"
    if tool == "WebFetch":
        return f"fetch {short(tool_input.get('url'), 100)}"
    if tool == "WebSearch":
        return f"search the web for {short(tool_input.get('query'), 100)}"
    if tool.startswith("mcp__"):
        _, server, name = ([*tool.split("__", 2), "", ""])[:3]
        return f"use the {name.replace('_', ' ')} tool from {server}"
    return f"use {tool}"


def requests_for(event: dict[str, Any]) -> list[dict[str, Any]]:
    """The bridge requests one hook event turns into (several for a multi-question ask)."""
    name = event.get("hook_event_name")
    project = Path(str(event.get("cwd") or "")).name
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") or {}
    if name == "PreToolUse" and tool == "AskUserQuestion":
        return [
            {
                "kind": "question",
                "text": q.get("question", ""),
                "options": [o.get("label", "") for o in q.get("options") or []],
                "multi": bool(q.get("multiSelect")),
                "project": project,
            }
            for q in tool_input.get("questions") or []
        ]
    if name == "PermissionRequest" and tool not in SKIP_PERMISSIONS:
        return [
            {"kind": "permission", "text": permission_text(tool, tool_input), "project": project}
        ]
    if name == "Notification":
        template = NOTICES.get(str(event.get("notification_type") or ""))
        if template:
            where = f" in {project}" if project else ""
            return [{"kind": "notify", "text": template.format(where=where), "project": project}]
    return []


def output_for(event: dict[str, Any], answers: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The hook's stdout for Claude Code, or None to let Claude Code ask as usual."""
    name = event.get("hook_event_name")
    if name == "PreToolUse":
        questions = (event.get("tool_input") or {}).get("questions") or []
        if (
            not questions
            or len(answers) != len(questions)
            or not all("answer" in a for a in answers)
        ):
            return None  # every question needs an answer, or Claude Code asks them all itself
        chosen = {
            q.get("question", ""): a["answer"] for q, a in zip(questions, answers, strict=True)
        }
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "allow",
                "permissionDecisionReason": "Answered by voice through Jarvis",
                "updatedInput": {**event["tool_input"], "answers": chosen},
            }
        }
    if name == "PermissionRequest" and answers and "allow" in answers[0]:
        if answers[0]["allow"]:
            decision: dict[str, Any] = {"behavior": "allow"}
        else:
            decision = {"behavior": "deny", "message": "The user said no through Jarvis."}
        return {"hookSpecificOutput": {"hookEventName": "PermissionRequest", "decision": decision}}
    return None


def run_hook(raw: str, data_dir: Path, *, http: httpx.Client | None = None) -> str:
    """Handle one hook event; returns what to print (often nothing)."""
    try:
        event = json.loads(raw)
        wanted = requests_for(event)
        if not wanted:
            return ""
        address = json.loads(bridge_file(data_dir).read_text("utf-8"))
    except (OSError, ValueError):
        return ""  # not a hook we handle, or Jarvis is not running
    client = http or httpx.Client(timeout=HOOK_TIMEOUT_S - 20)
    answers = []
    try:
        for request in wanted:
            response = client.post(
                f"http://127.0.0.1:{address['port']}/bridge",
                json=request,
                headers={"Authorization": f"Bearer {address['token']}"},
            )
            if response.status_code != 200:
                return ""
            answers.append(response.json())
    except (httpx.HTTPError, ValueError, KeyError):
        log.info("The Claude Code bridge could not reach Jarvis", exc_info=True)
        return ""
    finally:
        if http is None:
            client.close()
    result = output_for(event, answers)
    return json.dumps(result) if result else ""


# Installing the hooks into Claude Code's user settings (~/.claude/settings.json)


def hook_command(project: Path) -> dict[str, Any]:
    uv = shutil.which("uv") or "uv"
    return {
        "type": "command",
        "command": uv,
        "args": ["run", "--quiet", "--project", str(project), "jarvis", MARK],
        "timeout": HOOK_TIMEOUT_S,
    }


def install(settings_path: Path, project: Path) -> dict[str, Any]:
    """Add Jarvis's hooks (keeping everything else) and return the new settings."""
    settings = _load(settings_path)
    uninstall_from(settings)
    hooks = settings.setdefault("hooks", {})
    command = hook_command(project)
    hooks.setdefault("PreToolUse", []).append({"matcher": "AskUserQuestion", "hooks": [command]})
    hooks.setdefault("PermissionRequest", []).append({"matcher": "*", "hooks": [command]})
    hooks.setdefault("Notification", []).append({"hooks": [command]})
    _save(settings_path, settings)
    return settings


def uninstall(settings_path: Path) -> bool:
    settings = _load(settings_path)
    removed = uninstall_from(settings)
    if removed:
        _save(settings_path, settings)
    return removed


def uninstall_from(settings: dict[str, Any]) -> bool:
    removed = False
    hooks: dict[str, list[dict[str, Any]]] = settings.get("hooks") or {}
    for event in list(hooks):
        kept = [group for group in hooks[event] if not _is_ours(group)]
        removed = removed or len(kept) != len(hooks[event])
        if kept:
            hooks[event] = kept
        else:
            del hooks[event]
    return removed


def installed(settings_path: Path) -> bool:
    groups = (_load(settings_path).get("hooks") or {}).values()
    return any(_is_ours(group) for groups_ in groups for group in groups_)


def _is_ours(group: dict[str, Any]) -> bool:
    return any(MARK in json.dumps(hook) for hook in group.get("hooks") or [])


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    data = json.loads(path.read_text("utf-8") or "{}")
    if not isinstance(data, dict):
        raise ValueError(f"{path} does not hold a JSON object")
    return data


def _save(path: Path, settings: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        backup = path.with_suffix(".json.jarvis-backup")
        backup.write_text(path.read_text("utf-8"), "utf-8")
    path.write_text(json.dumps(settings, indent=2) + "\n", "utf-8")
