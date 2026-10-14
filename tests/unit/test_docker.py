"""Docker tools against a fake docker CLI. No real containers are touched."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from jarvis.tools.apps import docker
from jarvis.tools.base import ToolError
from tests.conftest import FakeChannel, MakeApp, reply


def _container(name: str, image: str, state: str) -> dict[str, str]:
    return {"Names": name, "Image": image, "State": state, "Status": state, "Ports": ""}


CONTAINERS = [
    _container("attal-qa-postgres-1", "postgres:17", "running"),
    _container("attal-qa-backend-1", "attal-qa-backend", "exited"),
    _container("attal-dev-backend-1", "attal-dev-backend", "running"),
]


@pytest.fixture
def docker_cli(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, ...]]:
    calls: list[tuple[str, ...]] = []

    async def fake_run(*args: str, timeout_s: float = 20) -> str:
        calls.append(args)
        if args[0] == "ps":
            return "\n".join(json.dumps(c) for c in CONTAINERS)
        if args[0] == "logs":
            return "line 1\nline 2\n"
        return args[1] + "\n"

    monkeypatch.setattr(docker, "run_docker", fake_run)
    return calls


async def test_list_shows_running_containers(make_app: MakeApp, docker_cli: list) -> None:
    h = make_app([reply("", ("docker_list", {})), reply("Two are running.")])
    await h.app.agent.run_turn("what containers are running")
    data = json.loads(h.audit()[0]["result_json"])
    assert [c["name"] for c in data] == ["attal-qa-postgres-1", "attal-dev-backend-1"]


async def test_stop_resolves_the_name_and_asks_first(make_app: MakeApp, docker_cli: list) -> None:
    h = make_app([reply("", ("docker_stop", {"container": "postgres"})), reply("Stopped.")])
    await h.app.agent.run_turn("stop the postgres container")
    (request,) = h.channel.requests
    assert request.summary == "Stop container attal-qa-postgres-1 (postgres:17)"
    assert ("stop", "attal-qa-postgres-1") in docker_cli


async def test_declined_stop_runs_nothing(make_app: MakeApp, docker_cli: list) -> None:
    h = make_app(
        [reply("", ("docker_stop", {"container": "postgres"})), reply("Okay.")],
        channel=FakeChannel(confirm=False),
    )
    await h.app.agent.run_turn("stop postgres")
    assert all(call[0] != "stop" for call in docker_cli)
    assert h.audit()[0]["decision"] == "denied"


async def test_start_only_considers_stopped_containers(make_app: MakeApp, docker_cli: list) -> None:
    h = make_app([reply("", ("docker_start", {"container": "backend"})), reply("Started.")])
    await h.app.agent.run_turn("start the backend")
    assert h.channel.requests[0].summary.startswith("Start container attal-qa-backend-1")


def test_ambiguous_names_are_reported() -> None:
    containers = [docker.Container(c["Names"], c["Image"], c["State"], "", "") for c in CONTAINERS]
    with pytest.raises(ToolError, match="could be"):
        docker.pick_container("backend", containers)
    assert docker.pick_container("attal-dev-backend-1", containers).name == "attal-dev-backend-1"
    with pytest.raises(ToolError, match="No container matches"):
        docker.pick_container("redis", containers)


async def test_engine_down_gives_a_helpful_message(monkeypatch: pytest.MonkeyPatch) -> None:
    class Proc:
        returncode = 1

        async def communicate(self) -> tuple[bytes, bytes]:
            return b"", b"error during connect: this error may indicate the daemon is not running"

    async def fake_exec(*args: Any, **kwargs: Any) -> Proc:
        return Proc()

    monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_exec)
    with pytest.raises(ToolError, match="Docker engine is not running"):
        await docker.run_docker("ps")
