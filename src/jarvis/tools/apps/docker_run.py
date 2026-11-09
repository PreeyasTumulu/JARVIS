"""Run a project's code in a container, exactly as config says (ADR-106).

`[docker.runners.<name>]` gives the image, the command, and the folder. What the user says only
picks a runner (by its name, or a Claude project's `runner`), so speech never writes a command
line. The container is shut in: the folder is mounted read-only at /work, there is no network
unless the runner turns it on, memory, CPUs and processes are capped, it has no capabilities and
cannot gain privileges, and it is removed when it ends. A run that passes its time is killed.
"""

from __future__ import annotations

import asyncio
import re
import subprocess
import time
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from jarvis.config import DockerRunner, Settings
from jarvis.platform.known_folders import expand_folder
from jarvis.tools.apps.docker import _ENGINE_DOWN, ENGINE_DOWN_MESSAGE
from jarvis.tools.apps.docker_up import _IMAGE
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.secrets import redact_secrets

RUNNER_MATCH = 80
OUTPUT_LINES = 30
PIDS_LIMIT = 512


def runner_names(settings: Settings) -> dict[str, str]:
    """Every name that picks a runner: the runners' own and the Claude projects that name one."""
    names = {name: name for name in settings.docker.runners}
    for project, cfg in settings.claude.projects.items():
        if cfg.runner and cfg.runner in settings.docker.runners:
            names.setdefault(project, cfg.runner)
    return names


def choose_runner(settings: Settings, spoken: str) -> str:
    names = runner_names(settings)
    if not names:
        raise ToolError(
            "No Docker runners are set up. Add one to config/local.toml, for example "
            '[docker.runners.jarvis] image = "python:3.12-slim" '
            'command = ["python", "main.py"] folder = "C:/Projects/JARVIS".'
        )
    words = re.sub(
        r"\b(my|the|code|project|in|on|docker|container|it|run)\b", " ", spoken.casefold()
    )
    query = " ".join(words.split())
    if not query and len(set(names.values())) == 1:
        return next(iter(names.values()))
    best = process.extractOne(
        query or spoken.casefold(), {n: n.casefold() for n in names}, scorer=fuzz.WRatio
    )
    if best is None or best[1] < RUNNER_MATCH:
        raise ToolError(f"No Docker runner matches '{spoken}'. Runners: {', '.join(names)}.")
    return names[str(best[2])]


def checked_folder(runner: DockerRunner, name: str) -> Path:
    folder = expand_folder(runner.folder)
    if any(ch in str(folder) for ch in ',"'):
        raise ToolError(
            f"The {name} runner's folder has a comma or quote, which Docker can't mount."
        )
    if not folder.is_dir():
        raise ToolError(f"The {name} runner's folder {folder} does not exist.")
    return folder


def checked_image(runner: DockerRunner, name: str) -> str:
    repository, _, tag = runner.image.partition(":")
    image = repository.casefold() + (f":{tag}" if tag else "")
    if not _IMAGE.match(image):
        raise ToolError(f"The {name} runner's image '{runner.image}' is not an image name.")
    return image


def run_args(runner: DockerRunner, folder: Path, image: str, container: str) -> list[str]:
    args = ["run", "--rm", "--name", container, "--init"]
    if not runner.network:
        args += ["--network", "none"]
    args += ["--memory", runner.memory, "--cpus", f"{runner.cpus:g}"]
    args += ["--pids-limit", str(PIDS_LIMIT), "--cap-drop", "ALL"]
    args += ["--security-opt", "no-new-privileges"]
    args += ["--mount", f"type=bind,source={folder},target=/work,readonly", "--workdir", "/work"]
    return [*args, image, *runner.command]


def container_name(name: str) -> str:
    clean = re.sub(r"[^A-Za-z0-9_.-]", "-", name)[:40].strip("-.") or "runner"
    return f"jarvis-run-{clean}-{int(time.time())}"


def last_lines(text: str, count: int = OUTPUT_LINES) -> str:
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return redact_secrets("\n".join(lines[-count:]))[0]


async def run_container(args: list[str], container: str, timeout_s: float) -> tuple[int, str]:
    """The exit code and the output (stdout and stderr together). Kills it at the deadline."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except FileNotFoundError:
        raise ToolError("The docker command is not installed or not on PATH.") from None
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        killer = await asyncio.create_subprocess_exec(
            "docker",
            "kill",
            container,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        await killer.wait()
        proc.kill()
        raise ToolError(f"The run passed its {timeout_s:.0f} seconds, so I stopped it.") from None
    text = out.decode("utf-8", "replace")
    if proc.returncode == 125 and any(m in text.casefold() for m in _ENGINE_DOWN):
        raise ToolError(ENGINE_DOWN_MESSAGE)
    return int(proc.returncode or 0), text


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=3700)
async def docker_run_code(ctx: ToolContext, runner: str) -> ToolResult:
    """Run one of the user's projects in its Docker image from config and report the output,
    for "run the jarvis code in Docker" or "test it in a container". The image, the command,
    and the folder come from config; nothing else can be passed.

    Args:
        runner: The runner or project name as the user said it, for example "jarvis".
    """
    cfg = ctx.settings.docker.runners[runner]
    folder = checked_folder(cfg, runner)
    image = checked_image(cfg, runner)
    container = container_name(runner)
    started = time.monotonic()
    code, output = await run_container(
        run_args(cfg, folder, image, container), container, cfg.timeout_s
    )
    seconds = round(time.monotonic() - started)
    tail = last_lines(output)
    last = tail.splitlines()[-1] if tail else "no output"
    verdict = "finished" if code == 0 else f"failed with exit code {code}"
    return ToolResult.success(
        data={"runner": runner, "exit_code": code, "seconds": seconds, "output": tail},
        speech=f"The {runner} run {verdict} after {seconds} seconds. The last line: {last[:200]}",
    )


@docker_run_code.preparer
async def _prepare_run(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    name = choose_runner(ctx.settings, str(args.get("runner") or ""))
    cfg = ctx.settings.docker.runners[name]
    folder = await asyncio.to_thread(checked_folder, cfg, name)
    image = checked_image(cfg, name)
    network = "with internet" if cfg.network else "no internet"
    return Prepared(
        args={"runner": name},
        summary=(
            f"Run `{' '.join(cfg.command)}` in {image} with {folder} read-only, {network}, "
            f"{cfg.memory} memory, {cfg.cpus:g} CPUs, at most {cfg.timeout_s:.0f} s"
        ),
        risk=Risk.CONFIRM,
    )
