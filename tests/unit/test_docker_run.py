"""Phase 34: running a project's code in a shut-in container from config (ADR-106)."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest

from jarvis.config import DockerRunner
from jarvis.llm.types import ToolCall
from jarvis.tools.apps import docker_run as dr
from jarvis.tools.base import ToolContext, ToolError
from tests.conftest import Harness, MakeApp


def runner(folder: Path, **extra: Any) -> dict[str, Any]:
    return {
        "image": "Python:3.12-slim",
        "command": ["python", "-m", "pytest", "-q"],
        "folder": str(folder),
        **extra,
    }


async def call(h: Harness, **args: Any) -> Any:
    ctx = ToolContext(h.app.settings, h.channel, h.app.services, "s", "t")
    return await h.app.agent.executor.run(ToolCall("c1", "docker_run_code", json.dumps(args)), ctx)


@pytest.fixture
def ran(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []

    async def fake(args: list[str], container: str, timeout_s: float) -> tuple[int, str]:
        calls.append(args)
        return 1, "collected 3 items\n\nFAILED test_a.py::test_x token=sk-abc123def456ghi789\n"

    monkeypatch.setattr(dr, "run_container", fake)
    return calls


def test_the_container_is_shut_in(tmp_path: Path) -> None:
    cfg = DockerRunner(**runner(tmp_path))
    args = dr.run_args(cfg, tmp_path, "python:3.12-slim", "jarvis-run-x-1")
    joined = " ".join(args)
    assert args[:2] == ["run", "--rm"]
    assert "--network none" in joined
    assert "--cap-drop ALL" in joined
    assert "--security-opt no-new-privileges" in joined
    assert "--memory 1g --cpus 2" in joined
    assert f"type=bind,source={tmp_path},target=/work,readonly" in args
    assert args[-5:] == ["python:3.12-slim", "python", "-m", "pytest", "-q"]
    online = dr.run_args(DockerRunner(**runner(tmp_path, network=True)), tmp_path, "i", "c")
    assert "--network" not in online


async def test_it_asks_with_everything_it_will_do_then_reports(
    make_app: MakeApp, tmp_path: Path, ran: list[list[str]]
) -> None:
    h = make_app(overrides={"docker": {"runners": {"shop": runner(tmp_path)}}})
    outcome = await call(h, runner="the shop code")
    (request,) = h.channel.requests
    assert request.summary == (
        f"Run `python -m pytest -q` in python:3.12-slim with {tmp_path} read-only, "
        "no internet, 1g memory, 2 CPUs, at most 300 s"
    )
    assert outcome.result.data["exit_code"] == 1
    assert outcome.result.speech.startswith("The shop run failed with exit code 1 after")
    assert "sk-abc123" not in outcome.result.data["output"]
    assert len(ran) == 1


async def test_a_claude_project_picks_its_runner(
    make_app: MakeApp, tmp_path: Path, ran: list[list[str]]
) -> None:
    h = make_app(
        overrides={
            "docker": {"runners": {"py": runner(tmp_path)}},
            "claude": {"projects": {"jarvis": {"folder": str(tmp_path), "runner": "py"}}},
        }
    )
    outcome = await call(h, runner="jarvis")
    assert outcome.result.data["runner"] == "py"


async def test_no_runner_says_how_to_add_one(make_app: MakeApp, ran: list[list[str]]) -> None:
    h = make_app()
    outcome = await call(h, runner="shop")
    assert "docker.runners" in outcome.result.error
    assert ran == []


async def test_a_missing_folder_never_runs(
    make_app: MakeApp, tmp_path: Path, ran: list[list[str]]
) -> None:
    h = make_app(overrides={"docker": {"runners": {"shop": runner(tmp_path / "gone")}}})
    outcome = await call(h, runner="shop")
    assert "does not exist" in outcome.result.error
    assert ran == []


def test_only_image_names_and_mountable_folders(tmp_path: Path) -> None:
    with pytest.raises(ToolError, match="not an image name"):
        dr.checked_image(DockerRunner(**{**runner(tmp_path), "image": "--privileged"}), "x")
    odd = tmp_path / "a,b"
    odd.mkdir()
    with pytest.raises(ToolError, match="comma or quote"):
        dr.checked_folder(DockerRunner(**runner(odd)), "x")


async def test_a_run_past_its_time_is_killed(monkeypatch: pytest.MonkeyPatch) -> None:
    killed: list[tuple[str, ...]] = []

    class Hanging:
        returncode = None

        async def communicate(self) -> tuple[bytes, bytes]:
            await asyncio.Event().wait()
            return b"", b""

        def kill(self) -> None:
            killed.append(("proc",))

    class Done:
        async def wait(self) -> int:
            return 0

    async def fake_exec(*args: str, **kwargs: Any) -> Any:
        if args[1] == "kill":
            killed.append(args)
            return Done()
        return Hanging()

    monkeypatch.setattr(dr.asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(ToolError, match="passed its"):
        await dr.run_container(["run"], "jarvis-run-x-1", 0.01)
    assert ("docker", "kill", "jarvis-run-x-1") in killed
