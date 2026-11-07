"""Start Docker work and wait until it is ready: "start the shop project", "run redis" (ADR-092).

- A compose project listed in `[docker.projects.<name>]` (its folder): `docker compose up -d`.
- An image: `docker run -d`, with only a container name and published ports. Nothing else
  (commands, volumes, environment, privileges) can be passed, so a request cannot become an
  arbitrary command line.

Both ask first. Then Jarvis waits, up to `[docker] ready_timeout_s`, until every container is
healthy (when the image has a health check) or running with its published ports answering on
this computer, and says how long it took. A container that stops while starting is reported
with the end of its log.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from jarvis.platform.known_folders import expand_folder
from jarvis.tools.apps.docker import run_docker
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.secrets import redact_secrets

_IMAGE = re.compile(
    r"^[a-z0-9][a-z0-9._/-]{0,199}(:[A-Za-z0-9._-]{1,128})?(@sha256:[a-f0-9]{64})?$"
)
_PORT = re.compile(r"^(\d{1,5})(?::(\d{1,5}))?$")
_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,62}$")
_PUBLISHED = re.compile(r"->\s*(?:0\.0\.0\.0|\[::\]|127\.0\.0\.1|::):(\d+)")
PROJECT_MATCH = 85
POLL_S = 1.0


@dataclass(frozen=True)
class Readiness:
    name: str
    ready: bool
    detail: str  # "healthy", "port 6379 answers", "running", or why not


def check_ports(ports: list[str]) -> list[str]:
    checked = []
    for port in ports:
        found = _PORT.match(port.strip())
        if found is None or any(int(p) > 65535 or int(p) == 0 for p in found.groups() if p):
            raise ToolError(f"'{port}' is not a port mapping like 8080:80 or 6379.")
        checked.append(f"{found[1]}:{found[2] or found[1]}")
    return checked


def published_ports(text: str) -> list[int]:
    """Host ports from `docker port` output ("6379/tcp -> 0.0.0.0:6379")."""
    return sorted({int(port) for port in _PUBLISHED.findall(text)})


async def port_answers(port: int) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection("127.0.0.1", port), 1.0)
    except (OSError, TimeoutError):
        return False
    writer.close()
    with contextlib.suppress(OSError):
        await writer.wait_closed()
    return True


async def readiness(container: str) -> Readiness:
    state = json.loads(await run_docker("inspect", "--format", "{{json .State}}", container))
    health = (state.get("Health") or {}).get("Status")
    if not state.get("Running"):
        status = state.get("Status", "stopped")
        return Readiness(container, False, f"stopped ({status}, exit code {state.get('ExitCode')})")
    if health:
        return Readiness(container, health == "healthy", health)
    ports = published_ports(await run_docker("port", container))
    for port in ports:
        if not await port_answers(port):
            return Readiness(container, False, f"port {port} not answering yet")
    detail = f"port {', '.join(map(str, ports))} answers" if ports else "running"
    return Readiness(container, True, detail)


async def wait_ready(containers: list[str], timeout_s: float) -> tuple[list[Readiness], float]:
    started = time.perf_counter()
    while True:
        states = [await readiness(name) for name in containers]
        stopped = [s for s in states if s.detail.startswith("stopped")]
        done = all(s.ready for s in states) or stopped
        if done or time.perf_counter() - started >= timeout_s:
            return states, time.perf_counter() - started
        await asyncio.sleep(POLL_S)


def project_folder(ctx: ToolContext, spoken: str) -> tuple[str, Path] | None:
    projects = ctx.settings.docker.projects
    if not projects:
        return None
    best = process.extractOne(
        spoken.casefold(), {n: n.casefold() for n in projects}, scorer=fuzz.WRatio
    )
    if best is None or best[1] < PROJECT_MATCH:
        return None
    name = best[2]
    return name, expand_folder(projects[name].path)


async def compose_containers(folder: Path) -> list[str]:
    output = await run_docker(
        "compose", "--project-directory", str(folder), "ps", "--all", "--format", "json"
    )
    names: list[str] = []
    for line in output.splitlines():
        line = line.strip()
        if not line:
            continue
        items: Any = json.loads(line)
        for item in items if isinstance(items, list) else [items]:
            if isinstance(item, dict) and item.get("Name"):
                names.append(str(item["Name"]))
    return names


def _spoken(states: list[Readiness], seconds: float, what: str) -> str:
    stopped = [s for s in states if not s.ready]
    if not stopped:
        return (
            f"{what} is ready, in {seconds:.0f} seconds." if seconds >= 1 else f"{what} is ready."
        )
    first = stopped[0]
    return f"{what} started, but {first.name} is {first.detail} after {seconds:.0f} seconds."


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=600)
async def docker_up(
    ctx: ToolContext, target: str, ports: list[str] | None = None, name: str | None = None
) -> ToolResult:
    """Start a Docker compose project or run an image, then wait until it is ready, for
    "start the shop project" or "run redis on port 6379". Asks the user first.

    Args:
        target: A project name from the user's config ("shop"), or an image such as "redis:7".
        ports: For an image only: published ports, for example ["6379:6379"] or ["8080:80"].
        name: For an image only: the container name, for example "redis".
    """
    timeout = ctx.settings.docker.ready_timeout_s
    project = project_folder(ctx, target)
    if project is not None:
        label, folder = project
        await run_docker("compose", "--project-directory", str(folder), "up", "-d", timeout_s=300)
        containers = await compose_containers(folder)
        what = f"The {label} project"
    else:
        args = ["run", "-d"]
        if name:
            args += ["--name", name]
        for mapping in ports or []:
            args += ["-p", mapping]
        container = (await run_docker(*args, target, timeout_s=300)).strip().splitlines()[-1][:64]
        containers = [name or container]
        what = name or target
    if not containers:
        raise ToolError("Docker started nothing: the project has no services.")
    states, seconds = await wait_ready(containers, timeout)
    data: dict[str, Any] = {
        "containers": [s.__dict__ for s in states],
        "seconds": round(seconds, 1),
    }
    not_ready = [s for s in states if not s.ready]
    if not_ready and not_ready[0].detail.startswith("stopped"):
        logs = await run_docker("logs", "--tail", "15", not_ready[0].name)
        data["logs"] = redact_secrets(logs[-2000:])[0]
    return ToolResult.success(data=data, speech=_spoken(states, seconds, what))


@docker_up.preparer
async def _prepare_up(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    target = " ".join(str(args["target"]).split())
    project = project_folder(ctx, target)
    if project is not None:
        label, folder = project
        if not await asyncio.to_thread(folder.is_dir):
            raise ToolError(f"The {label} project's folder {folder} does not exist.")
        return Prepared(
            args={"target": label, "ports": None, "name": None},
            summary=f"Start the {label} project (docker compose up in {folder})",
            risk=Risk.CONFIRM,
        )
    repository, _, tag = target.partition(":")
    image = repository.casefold() + (f":{tag}" if tag else "")  # names are lower case, tags not
    if not _IMAGE.match(image):
        known = ", ".join(ctx.settings.docker.projects) or "none in config yet"
        raise ToolError(
            f"'{target}' is neither a Docker image name nor a project in config "
            f"(projects: {known})."
        )
    ports = check_ports(list(args.get("ports") or []))
    name = (args.get("name") or "").strip() or None
    if name is not None and not _NAME.match(name):
        raise ToolError(f"'{name}' is not a valid container name.")
    shown = f" as {name}" if name else ""
    on = f", ports {', '.join(ports)}" if ports else ""
    return Prepared(
        args={"target": image, "ports": ports or None, "name": name},
        summary=f"Run the image {image}{shown}{on}",
        risk=Risk.CONFIRM,
    )
