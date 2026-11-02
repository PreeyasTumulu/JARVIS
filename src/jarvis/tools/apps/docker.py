"""Docker through its CLI: list containers, read logs, start and stop them (those two ask first)."""

from __future__ import annotations

import asyncio
import json
import subprocess
from dataclasses import asdict, dataclass
from typing import Any

from rapidfuzz import fuzz

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.secrets import hide_secrets

_ENGINE_DOWN = ("error during connect", "cannot connect to the docker daemon", "pipe/docker")
ENGINE_DOWN_MESSAGE = (
    "The Docker engine is not running. Open Docker Desktop (open_app), wait about a minute, "
    "then try again."
)


@dataclass(frozen=True)
class Container:
    name: str
    image: str
    state: str  # running, exited, paused, ...
    status: str  # human text, for example "Up 2 hours"
    ports: str


async def run_docker(*args: str, timeout_s: float = 20) -> str:
    """Run the docker CLI and return stdout plus stderr. Raises ToolError on failure."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        raise ToolError("The docker command is not installed or not on PATH.") from None
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        raise ToolError("Docker did not answer in time.") from None
    text, error = out.decode("utf-8", "replace"), err.decode("utf-8", "replace")
    if proc.returncode != 0:
        if any(marker in error.casefold() for marker in _ENGINE_DOWN):
            raise ToolError(ENGINE_DOWN_MESSAGE)
        raise ToolError(f"docker {args[0]} failed: {error.strip()[:300]}")
    return text + error


async def list_containers() -> list[Container]:
    output = await run_docker("ps", "--all", "--no-trunc", "--format", "{{json .}}")
    containers = []
    for line in output.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        item = json.loads(line)
        containers.append(
            Container(
                name=item.get("Names", ""),
                image=item.get("Image", ""),
                state=item.get("State", ""),
                status=item.get("Status", ""),
                ports=item.get("Ports", ""),
            )
        )
    return containers


def pick_container(spoken: str, containers: list[Container]) -> Container:
    """Fuzzy match a spoken name ("postgres") to one container, or explain the choices."""
    if not containers:
        raise ToolError("There are no matching containers.")
    query = spoken.casefold().strip()
    for container in containers:
        if container.name.casefold() == query:
            return container
    scored = sorted(
        (
            (max(fuzz.WRatio(query, c.name.casefold()), fuzz.WRatio(query, c.image.casefold())), c)
            for c in containers
        ),
        key=lambda pair: pair[0],
        reverse=True,
    )
    best_score, best = scored[0]
    if best_score < 70:
        names = ", ".join(c.name for _, c in scored[:5])
        raise ToolError(f"No container matches '{spoken}'. Containers: {names}.")
    close = [c.name for score, c in scored[1:] if score >= best_score - 3]
    if close:
        options = ", ".join([best.name, *close][:4])
        raise ToolError(f"'{spoken}' could be {options}. Ask the user which container.")
    return best


async def _resolve(spoken: str, *, states: set[str] | None = None) -> Container:
    containers = await list_containers()
    if states is not None:
        containers = [c for c in containers if c.state in states]
    return pick_container(spoken, containers)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=30)
async def docker_list(ctx: ToolContext, include_stopped: bool = False) -> ToolResult:
    """List Docker containers with their image, state, and ports. Starts nothing: to open
    Docker Desktop itself, use open_app.

    Args:
        include_stopped: Also list containers that are not running.
    """
    containers = await list_containers()
    shown = containers if include_stopped else [c for c in containers if c.state == "running"]
    if not shown:
        stopped = len(containers)
        return ToolResult.success(data=[], speech=f"No containers are running ({stopped} stopped).")
    names = ", ".join(c.name for c in shown[:3])
    more = f" and {len(shown) - 3} more" if len(shown) > 3 else ""
    state = "containers" if include_stopped else "containers are running"
    speech = f"{len(shown)} {state}: {names}{more}."
    return ToolResult.success(data=[asdict(c) for c in shown], speech=speech)


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=30)
async def docker_logs(ctx: ToolContext, container: str, lines: int = 30) -> ToolResult:
    """Show the recent log output of one Docker container ("logs of the backend").

    Args:
        container: The container name, or part of it, for example "postgres".
        lines: How many of the latest lines to show (1 to 200).
    """
    count = max(1, min(200, lines))
    output = await run_docker("logs", "--tail", str(count), container)
    data: dict[str, object] = {"container": container, "logs": output[-8000:]}
    return ToolResult.success(data=hide_secrets(data, "logs"))


@docker_logs.preparer
async def _prepare_logs(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    found = await _resolve(args["container"])
    return Prepared(
        args={"container": found.name, "lines": args["lines"]}, summary=f"Show logs of {found.name}"
    )


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=60)
async def docker_start(ctx: ToolContext, container: str) -> ToolResult:
    """Start a stopped Docker container. Asks the user first.

    Args:
        container: The container name, or part of it, for example "postgres".
    """
    await run_docker("start", container, timeout_s=55)
    return ToolResult.success(data={"started": container}, speech=f"Started {container}.")


@docker_start.preparer
async def _prepare_start(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    found = await _resolve(args["container"], states={"exited", "created", "paused", "dead"})
    return Prepared(
        args={"container": found.name},
        summary=f"Start container {found.name} ({found.image})",
        risk=Risk.CONFIRM,
    )


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=60)
async def docker_stop(ctx: ToolContext, container: str) -> ToolResult:
    """Stop a running Docker container. Asks the user first.

    Args:
        container: The container name, or part of it, for example "postgres".
    """
    await run_docker("stop", container, timeout_s=55)
    return ToolResult.success(data={"stopped": container}, speech=f"Stopped {container}.")


@docker_stop.preparer
async def _prepare_stop(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    found = await _resolve(args["container"], states={"running", "restarting"})
    return Prepared(
        args={"container": found.name},
        summary=f"Stop container {found.name} ({found.image})",
        risk=Risk.CONFIRM,
    )
