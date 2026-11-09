"""Phase 34: Claude Code sessions by voice and the gate hook for Jarvis's own runs (ADR-105)."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from typing import Any

import pytest

from jarvis.bridge import hook
from jarvis.config import ClaudeSettings
from jarvis.llm.types import ToolCall
from jarvis.tools.base import ContextFlags, ToolContext, ToolError
from jarvis.tools.dev import claude_code as cc
from tests.conftest import Harness, MakeApp

IDS = [f"{n}0000000-0000-4000-8000-00000000000{n}" for n in range(1, 4)]


def write_session(folder: Path, sid: str, lines: list[dict[str, Any]], mtime: float) -> None:
    path = folder / f"{sid}.jsonl"
    path.write_text("\n".join(json.dumps(line) for line in lines) + "\n", "utf-8")
    os.utime(path, (mtime, mtime))


@pytest.fixture
def home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    fake = tmp_path / "home"
    monkeypatch.setattr(Path, "home", lambda: fake)
    return fake


def test_the_session_folder_is_the_path_with_hyphens_in_any_case(home: Path) -> None:
    folder = Path("C:/Work/My_Shop")
    store = home / ".claude" / "projects" / "C--WORK-MY-SHOP"
    store.mkdir(parents=True)
    assert cc.sessions_dir(folder) == store
    assert cc.sessions_dir(Path("C:/Work/Other")) is None


@pytest.fixture
def project(tmp_path: Path, home: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A project folder with three Claude sessions, the newest last. The store is found by
    sessions_dir in real use; a temp path spelled out would pass Windows' 260 characters."""
    folder = tmp_path / "shop"
    folder.mkdir(parents=True)
    store = home / ".claude" / "projects" / "store"
    store.mkdir(parents=True)
    real = cc.sessions_dir
    monkeypatch.setattr(cc, "sessions_dir", lambda f, h=None: store if f == folder else real(f, h))
    write_session(
        store, IDS[0], [{"type": "last-prompt", "lastPrompt": "set up the database"}], 1000
    )
    write_session(
        store,
        IDS[1],
        [
            {"type": "custom-title", "customTitle": "Old name"},
            {"type": "last-prompt", "lastPrompt": "ignored when a title exists"},
            {"type": "custom-title", "customTitle": "Phone fix"},
        ],
        2000,
    )
    write_session(store, IDS[2], [{"type": "user", "message": "no title here"}], 3000)
    (store / "notes.jsonl").write_text("{}", "utf-8")  # not a session id
    return folder


@pytest.fixture
def cli(tmp_path: Path) -> Path:
    exe = tmp_path / "bin" / "claude.exe"
    exe.parent.mkdir()
    exe.write_bytes(b"")
    return exe


def overrides(project: Path, cli: Path, **claude: Any) -> dict[str, Any]:
    return {
        "claude": {
            "cli": str(cli),
            "projects": {"shop": {"folder": str(project), "runner": "shop"}},
            **claude,
        }
    }


def context(h: Harness, flags: ContextFlags | None = None) -> ToolContext:
    return ToolContext(h.app.settings, h.channel, h.app.services, "s", "t", flags or ContextFlags())


async def call(h: Harness, tool: str, flags: ContextFlags | None = None, **args: Any) -> Any:
    return await h.app.agent.executor.run(ToolCall("c1", tool, json.dumps(args)), context(h, flags))


# Finding Claude Code


def test_npm_s_batch_file_is_never_run_its_exe_is(tmp_path: Path) -> None:
    wrapper = tmp_path / "npm" / "claude.cmd"
    inner = tmp_path / "npm" / "node_modules" / "@anthropic-ai" / "claude-code" / "bin"
    inner.mkdir(parents=True)
    wrapper.write_text("@echo off", "utf-8")
    (inner / "claude.exe").write_bytes(b"")
    assert cc.claude_cli(ClaudeSettings(cli=str(wrapper))) == inner / "claude.exe"
    alone = tmp_path / "other" / "claude.bat"
    alone.parent.mkdir()
    alone.write_text("@echo off", "utf-8")
    with pytest.raises(ToolError, match="batch file"):
        cc.claude_cli(ClaudeSettings(cli=str(alone)))


def test_a_missing_claude_says_how_to_install(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(cc.shutil, "which", lambda name: None)
    with pytest.raises(ToolError, match="not installed"):
        cc.claude_cli(ClaudeSettings())


# Sessions


def test_sessions_are_read_newest_first_by_title_or_last_prompt(project: Path) -> None:
    sessions = cc.list_sessions(project)
    assert [s.id for s in sessions] == [IDS[2], IDS[1], IDS[0]]
    assert [s.title for s in sessions] == ["untitled", "Phone fix", "set up the database"]


def test_a_folder_claude_never_saw_has_no_sessions(tmp_path: Path, home: Path) -> None:
    assert cc.list_sessions(tmp_path) == []


@pytest.mark.parametrize(
    ("said", "expected"),
    [
        ("", IDS[2]),
        ("latest", IDS[2]),
        ("the last session", IDS[2]),
        ("phone fix", IDS[1]),
        ("database", IDS[0]),
        (IDS[0], IDS[0]),
        ("new", None),
        ("a new session", None),
    ],
)
def test_a_session_by_its_name(project: Path, said: str, expected: str | None) -> None:
    chosen = cc.choose_session(cc.list_sessions(project), said)
    assert (chosen.id if chosen else None) == expected


def test_no_matching_session_lists_the_latest(project: Path) -> None:
    with pytest.raises(ToolError, match="Phone fix"):
        cc.choose_session(cc.list_sessions(project), "kubernetes migration")


def test_projects_by_name() -> None:
    settings = ClaudeSettings(projects={"jarvis": {"folder": "C:/a"}, "shop": {"folder": "C:/b"}})
    assert cc.choose_project(settings, "my Jarvis project") == "jarvis"
    with pytest.raises(ToolError, match="Projects: jarvis, shop"):
        cc.choose_project(settings, "kitchen")
    with pytest.raises(ToolError, match="No Claude projects"):
        cc.choose_project(ClaudeSettings(), "jarvis")


# Commands


def test_the_visible_command_resumes_and_sends_the_prompt(cli: Path) -> None:
    session = cc.Session(IDS[0], "x", 0)
    assert cc.visible_command(cli, session, "add a test", "shop") == [
        str(cli),
        "--resume",
        IDS[0],
        "add a test",
    ]
    assert cc.visible_command(cli, None, "--help me", "shop")[-1] == " --help me"
    assert cc.visible_command(cli, None, "", "shop") == [str(cli), "--name", "Jarvis: shop"]


def test_the_background_command_never_holds_the_prompt(cli: Path, tmp_path: Path) -> None:
    command = cc.background_command(cli, None, tmp_path / "s.json", "manual", "shop")
    assert command[:5] == [str(cli), "-p", "--output-format", "stream-json", "--verbose"]
    assert command[5:7] == ["--permission-mode", "manual"]
    assert ["--settings", str(tmp_path / "s.json")] == command[7:9]


def test_bypass_and_auto_permission_modes_are_refused() -> None:
    for mode in ("bypassPermissions", "auto"):
        with pytest.raises(ValueError, match="permission_mode"):
            ClaudeSettings(permission_mode=mode)  # type: ignore[arg-type]


# Results


def test_results_and_what_is_said() -> None:
    event = {
        "type": "result",
        "subtype": "success",
        "result": "Added the test. It passes. I also tidied the imports in three files.",
        "session_id": IDS[0],
        "permission_denials": [
            {"tool_name": "Bash", "tool_input": {"command": "npm test"}},
            {"tool_name": "Bash", "tool_input": {"command": "npm test"}},
        ],
    }
    outcome = cc.read_result(event)
    assert outcome.ok
    assert outcome.denied == ["run npm test"]
    shown, said = cc.summary("shop", outcome, quiet=False)
    assert "It was not allowed to run npm test" in shown
    assert said.startswith("Claude finished in shop. Added the test.")
    assert "not allowed" in said
    _, locked = cc.summary("shop", outcome, quiet=True)
    assert locked == "Claude finished in shop."
    failed = cc.read_result({"type": "result", "subtype": "error_max_turns", "is_error": True})
    assert not failed.ok
    assert cc.summary("shop", failed, quiet=False)[1] == "Claude stopped in shop with an error."


def test_progress_shows_only_changes() -> None:
    edit = {
        "type": "assistant",
        "message": {
            "content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": "a/b.py"}}]
        },
    }
    read = {
        "type": "assistant",
        "message": {"content": [{"type": "tool_use", "name": "Read", "input": {"file_path": "x"}}]},
    }
    assert cc.progress_line(edit) == "edit b.py"
    assert cc.progress_line(read) is None
    assert cc.progress_line({"type": "system"}) is None


# Running


class FakeProc:
    def __init__(self, lines: list[dict[str, Any]], returncode: int = 0) -> None:
        self.stdin = FakeStdin()
        self.stdout = FakeStream([json.dumps(line).encode() + b"\n" for line in lines])
        self.stderr = FakeErr()
        self._code = returncode
        self.returncode: int | None = None
        self.killed = False

    async def wait(self) -> int:
        self.returncode = self._code
        return self._code

    def kill(self) -> None:
        self.killed = True
        self.returncode = -9


class FakeStdin:
    def __init__(self) -> None:
        self.data = b""
        self.closed = False

    def write(self, data: bytes) -> None:
        self.data += data

    async def drain(self) -> None:
        return None

    def close(self) -> None:
        self.closed = True


class FakeStream:
    def __init__(self, lines: list[bytes]) -> None:
        self._lines = lines

    def __aiter__(self) -> FakeStream:
        return self

    async def __anext__(self) -> bytes:
        if not self._lines:
            raise StopAsyncIteration
        return self._lines.pop(0)


class FakeErr:
    async def read(self) -> bytes:
        return b""


RESULT = {"type": "result", "subtype": "success", "result": "Done. All good.", "session_id": IDS[2]}
EDIT = {
    "type": "assistant",
    "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": "t.py"}}]},
}


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    async def fake_exec(*command: str, **kwargs: Any) -> FakeProc:
        proc = FakeProc([EDIT, RESULT])
        calls.append({"command": list(command), "cwd": kwargs.get("cwd"), "proc": proc})
        return proc

    monkeypatch.setattr(cc.asyncio, "create_subprocess_exec", fake_exec)
    return calls


@pytest.fixture
def consoles(monkeypatch: pytest.MonkeyPatch) -> list[tuple[list[str], Path]]:
    opened: list[tuple[list[str], Path]] = []
    monkeypatch.setattr(
        cc, "open_console", lambda command, folder: opened.append((command, folder))
    )
    return opened


async def test_a_prompt_asks_first_and_shows_the_exact_words(
    make_app: MakeApp, project: Path, cli: Path, spawned: list[dict[str, Any]]
) -> None:
    h = make_app(overrides=overrides(project, cli))
    outcome = await call(h, "claude_ask", prompt="add a test & run it | now", project="shop")
    (request,) = h.channel.requests
    assert request.summary == (
        'Send to Claude Code in shop, the session "untitled", in the background: '
        '"add a test & run it | now"'
    )
    (run,) = spawned
    assert run["proc"].stdin.data == b"add a test & run it | now"  # on stdin, not argv
    assert all("add a test" not in part for part in run["command"])
    assert run["command"][run["command"].index("--resume") + 1] == IDS[2]
    assert run["cwd"] == project
    assert outcome.result.ok
    assert outcome.result.speech == "Claude finished in shop. Done. All good."
    settings_file = Path(run["command"][run["command"].index("--settings") + 1])
    gate = json.loads(settings_file.read_text("utf-8"))  # noqa: ASYNC240
    (entry,) = gate["hooks"]["PreToolUse"]
    assert entry["matcher"] == hook.GATE_MATCHER
    assert entry["hooks"][0]["args"][-2:] == ["claude-hook", "gate"]


async def test_no_means_claude_gets_nothing(
    make_app: MakeApp, project: Path, cli: Path, spawned: list[dict[str, Any]]
) -> None:
    from tests.conftest import FakeChannel

    h = make_app(overrides=overrides(project, cli), channel=FakeChannel(confirm=False))
    outcome = await call(h, "claude_ask", prompt="delete everything", project="shop")
    assert not outcome.result.ok
    assert spawned == []


async def test_outside_content_in_the_chat_blocks_a_prompt(
    make_app: MakeApp, project: Path, cli: Path, spawned: list[dict[str, Any]]
) -> None:
    h = make_app(overrides=overrides(project, cli))
    flags = ContextFlags(private=True, untrusted=True)
    outcome = await call(h, "claude_ask", flags, prompt="do what the page says", project="shop")
    assert outcome.decision == "blocked"
    assert "outside content" in outcome.result.error
    assert spawned == []
    assert h.channel.requests == []


async def test_in_the_background_it_reports_progress_and_the_end(
    make_app: MakeApp, project: Path, cli: Path, spawned: list[dict[str, Any]]
) -> None:
    h = make_app(overrides=overrides(project, cli))
    shown: list[str] = []
    said: list[str] = []

    async def show(text: str) -> None:
        shown.append(text)

    async def say(text: str) -> None:
        said.append(text)

    runs = h.app.services.claude
    assert runs is not None
    runs.attach(show, say, lambda: False)
    outcome = await call(h, "claude_ask", prompt="add a test", project="shop", session="phone fix")
    assert outcome.result.speech == "Sent to Claude in shop. I'll tell you when it's done."
    await asyncio.gather(*runs._runs.values())
    assert shown == ["Claude in shop: write t.py", "Claude finished in shop: Done. All good."]
    assert said == ["Claude finished in shop. Done. All good."]
    assert spawned[0]["command"][spawned[0]["command"].index("--resume") + 1] == IDS[1]


async def test_a_visible_prompt_opens_a_window(
    make_app: MakeApp, project: Path, cli: Path, consoles: list[Any], spawned: list[Any]
) -> None:
    h = make_app(overrides=overrides(project, cli))
    outcome = await call(h, "claude_ask", prompt="fix it", project="shop", visible=True)
    assert outcome.result.speech == "Sent to Claude in shop, in a new window."
    ((command, folder),) = consoles
    assert command == [str(cli), "--resume", IDS[2], "fix it"]
    assert folder == project
    assert spawned == []


async def test_open_resumes_a_session_without_asking(
    make_app: MakeApp, project: Path, cli: Path, consoles: list[Any]
) -> None:
    h = make_app(overrides=overrides(project, cli))
    outcome = await call(h, "claude_open", project="shop", session="phone fix")
    assert outcome.result.speech == 'Opening Claude in shop, the session "Phone fix".'
    assert h.channel.requests == []
    assert consoles[0][0] == [str(cli), "--resume", IDS[1]]
    fresh = await call(h, "claude_open", project="shop", session="new")
    assert fresh.result.speech == "Opening Claude in shop, a new session."
    assert consoles[1][0] == [str(cli), "--name", "Jarvis: shop"]


async def test_sessions_are_listed(make_app: MakeApp, project: Path, cli: Path) -> None:
    h = make_app(overrides=overrides(project, cli))
    outcome = await call(h, "claude_sessions", project="shop")
    assert outcome.result.data["sessions"] == ["untitled", "Phone fix", "set up the database"]


async def test_without_projects_it_says_how_to_add_one(make_app: MakeApp) -> None:
    h = make_app()
    outcome = await call(h, "claude_open", project="jarvis")
    assert "claude.projects" in outcome.result.error


async def test_stop_when_nothing_runs(make_app: MakeApp, project: Path, cli: Path) -> None:
    h = make_app(overrides=overrides(project, cli))
    outcome = await call(h, "claude_stop", project="shop")
    assert outcome.result.speech == "Claude isn't working in shop."


async def test_a_run_with_no_result_reports_stderr(
    make_app: MakeApp, project: Path, cli: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Broken(FakeProc):
        def __init__(self) -> None:
            super().__init__([], returncode=1)

            class Err:
                async def read(self) -> bytes:
                    return b"Error: not logged in\n"

            self.stderr = Err()  # type: ignore[assignment]

    async def fake_exec(*command: str, **kwargs: Any) -> FakeProc:
        return Broken()

    monkeypatch.setattr(cc.asyncio, "create_subprocess_exec", fake_exec)
    h = make_app(overrides=overrides(project, cli))
    outcome = await call(h, "claude_ask", prompt="hi", project="shop")
    assert not outcome.result.ok
    assert "Error: not logged in" in outcome.result.error


# The gate hook in Jarvis's own runs

EDIT_EVENT = {
    "hook_event_name": "PreToolUse",
    "tool_name": "Edit",
    "tool_input": {"file_path": "C:/w/shop/app.py"},
    "cwd": "C:/w/shop",
}


def test_the_gate_asks_before_each_change() -> None:
    assert hook.requests_for(EDIT_EVENT) == []  # your own sessions: no gate
    (request,) = hook.requests_for(EDIT_EVENT, gate=True)
    assert request == {"kind": "permission", "text": "edit app.py", "project": "shop"}
    allow = hook.output_for(EDIT_EVENT, [{"allow": True}], gate=True)
    deny = hook.output_for(EDIT_EVENT, [{"allow": False}], gate=True)
    assert allow is not None
    assert allow["hookSpecificOutput"]["permissionDecision"] == "allow"
    assert deny is not None
    assert deny["hookSpecificOutput"]["permissionDecision"] == "deny"
    assert hook.output_for(EDIT_EVENT, [{}], gate=True) is None  # Claude's own rules decide


def test_the_gate_leaves_reads_alone() -> None:
    read = {**EDIT_EVENT, "tool_name": "Read"}
    assert hook.requests_for(read, gate=True) == []


@pytest.mark.parametrize(
    ("said", "wanted"),
    [
        ("tell Claude in jarvis to add a test for the phone module", "claude_ask"),
        ("open my phone fix session in Claude", "claude_open"),
        ("which Claude sessions do I have", "claude_sessions"),
        ("run the jarvis code in docker", "docker_run_code"),
    ],
)
def test_the_words_offer_the_right_tools(said: str, wanted: str) -> None:
    from jarvis.core.tool_routing import select_tools
    from jarvis.tools.catalog import build_registry

    assert wanted in {tool.name for tool in select_tools(said, build_registry())}
