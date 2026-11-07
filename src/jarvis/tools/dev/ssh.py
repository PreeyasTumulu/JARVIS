"""SSH profiles from config: "connect to my server" opens a terminal with ssh (ADR-093).

`[ssh.profiles.<name>]` gives host, user, port, and an optional key file. Jarvis opens Windows
Terminal (or a console window when it is missing) running `ssh` to that profile, and then it is
your session: Jarvis never types into it, sends commands, or reads what it shows. Passwords
and host key questions are answered by you, in the terminal.
"""

from __future__ import annotations

import asyncio
import re
import shutil
import subprocess
from typing import Any

from rapidfuzz import fuzz, process

from jarvis.config import SshProfile
from jarvis.platform.known_folders import expand_folder
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool

PROFILE_MATCH = 80
# A leading "-" would make ssh read the host as an option, so names start with a letter or digit.
_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,252}$|^\[?[0-9a-fA-F:]{2,45}\]?$")
_USER = re.compile(r"^[A-Za-z0-9._-]{1,64}$")


def ssh_command(profile: SshProfile) -> list[str]:
    if not _HOST.match(profile.host):
        raise ToolError(f"'{profile.host}' is not a host name or address.")
    if profile.user and not _USER.match(profile.user):
        raise ToolError(f"'{profile.user}' is not a user name.")
    command = ["ssh", "-p", str(profile.port)]
    if profile.key:
        command += ["-i", str(expand_folder(profile.key))]
    command.append(f"{profile.user}@{profile.host}" if profile.user else profile.host)
    return command


def terminal_command(title: str, ssh: list[str]) -> list[str]:
    """Windows Terminal in a new tab named after the profile, or a plain console window."""
    terminal = shutil.which("wt")
    if terminal:
        return [terminal, "new-tab", "--title", title, *ssh]
    return ["cmd.exe", "/c", "start", title, *ssh]


def spawn(command: list[str]) -> None:
    subprocess.Popen(command, close_fds=True)


def choose_profile(ctx: ToolContext, spoken: str) -> str:
    profiles = ctx.settings.ssh.profiles
    if not profiles:
        raise ToolError(
            "No SSH profiles are set up. Add one to config/local.toml, for example "
            '[ssh.profiles.server] host = "203.0.113.5" user = "me".'
        )
    names = {name: name.casefold() for name in profiles}
    words = re.sub(r"\b(my|the|server|box|machine|vps|ssh|to|into)\b", " ", spoken.casefold())
    query = " ".join(words.split())
    if not query and len(profiles) == 1:
        return next(iter(profiles))
    best = process.extractOne(query or spoken.casefold(), names, scorer=fuzz.WRatio)
    if best is None or best[1] < PROFILE_MATCH:
        if len(profiles) == 1:
            return next(iter(profiles))
        raise ToolError(f"No SSH profile matches '{spoken}'. Profiles: {', '.join(profiles)}.")
    return str(best[2])


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=15)
async def ssh_connect(ctx: ToolContext, profile: str) -> ToolResult:
    """Open a terminal with an SSH session to one of the user's servers from config, for
    "connect to my server" or "ssh into the pi". The user types in it; Jarvis does not.

    Args:
        profile: The profile name as the user said it, for example "server" or "pi".
    """
    settings = ctx.settings.ssh.profiles[profile]
    command = terminal_command(profile, ssh_command(settings))
    await asyncio.to_thread(spawn, command)
    target = f"{settings.user}@{settings.host}" if settings.user else settings.host
    return ToolResult.success(
        data={"profile": profile, "target": target}, speech=f"Opening an SSH session to {profile}."
    )


@ssh_connect.preparer
async def _prepare_ssh(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    name = choose_profile(ctx, str(args["profile"]))
    profile = ctx.settings.ssh.profiles[name]
    ssh_command(profile)  # refuse a bad host or user before anything opens
    return Prepared(
        args={"profile": name}, summary=f"Open an SSH session to {name} ({profile.host})"
    )
