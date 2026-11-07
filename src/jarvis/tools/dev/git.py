"""Git in your repositories: what changed, commit, and push (ADR-094).

Repositories are the ones listed in `[git.repos]` (name to folder). `git_changes` shows the
status and the diff, so the local model can draft a commit message; the diff is private and
never leaves the laptop (git tools are private, which keeps them away from cloud models).
`git_commit` asks first with the message and the files, and commits what is staged, or every
change when nothing is staged. `git_push` asks again, naming the branch, the remote, and how
many commits go up, and never forces. Git never prompts in the background
(GIT_TERMINAL_PROMPT=0): a push that needs a password says so instead of hanging.
"""

from __future__ import annotations

import asyncio
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from jarvis.platform.known_folders import expand_folder
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.secrets import hide_secrets

REPO_MATCH = 80
MAX_DIFF_CHARS = 6000
MAX_MESSAGE_CHARS = 500
MAIN_BRANCHES = ("main", "master")
_BRANCH = re.compile(r"^[A-Za-z0-9._/-]{1,200}$")


async def run_git(folder: Path, *args: str, timeout_s: float = 30) -> str:
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": ""}
    try:
        proc = await asyncio.create_subprocess_exec(
            "git",
            "-C",
            str(folder),
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    except FileNotFoundError:
        raise ToolError("Git is not installed or not on PATH.") from None
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        proc.kill()
        raise ToolError(f"git {args[0]} did not finish within {timeout_s:.0f} seconds.") from None
    if proc.returncode != 0:
        message = err.decode("utf-8", "replace").strip() or out.decode("utf-8", "replace").strip()
        if "terminal prompts disabled" in message or "could not read Username" in message:
            message = "it needs a password or token, and Git cannot ask for one here"
        raise ToolError(f"git {args[0]} failed: {message[:400]}")
    return out.decode("utf-8", "replace")


def choose_repo(ctx: ToolContext, spoken: str) -> tuple[str, Path]:
    repos = ctx.settings.git.repos
    if not repos:
        raise ToolError(
            "No git repositories are set up. Add them to config/local.toml, for example "
            '[git.repos] jarvis = "C:/Projects/JARVIS".'
        )
    words = re.sub(r"\b(my|the|repo|repository|project|code|git|in|for)\b", " ", spoken.casefold())
    query = " ".join(words.split())
    if not query and len(repos) == 1:
        name = next(iter(repos))
        return name, expand_folder(repos[name])
    best = process.extractOne(
        query or spoken.casefold(), {n: n.casefold() for n in repos}, scorer=fuzz.WRatio
    )
    if best is None or best[1] < REPO_MATCH:
        raise ToolError(f"No repository matches '{spoken}'. Repositories: {', '.join(repos)}.")
    name = str(best[2])
    return name, expand_folder(repos[name])


async def current_branch(folder: Path) -> str:
    branch = (await run_git(folder, "rev-parse", "--abbrev-ref", "HEAD")).strip()
    if branch == "HEAD":
        raise ToolError(
            "The repository is not on a branch (detached HEAD), so I won't commit or push."
        )
    return branch


def changed_files(porcelain: str) -> list[str]:
    return [
        line[3:].strip()
        for line in porcelain.splitlines()
        if len(line) > 3 and not line.startswith("##")
    ]


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, untrusted=True, timeout_s=30)
async def git_changes(ctx: ToolContext, repo: str) -> ToolResult:
    """Show what changed in one of the user's git repositories: the branch, the changed files,
    and the diff. Use it before git_commit, to write the commit message from the diff.

    Args:
        repo: The repository name as the user said it, for example "jarvis" or "shop".
    """
    name, folder = choose_repo(ctx, repo)
    branch = await current_branch(folder)
    status = await run_git(folder, "status", "--porcelain=v1")
    files = changed_files(status)
    staged = (await run_git(folder, "diff", "--cached", "--name-only")).split()
    diff = await run_git(folder, "diff", "--cached" if staged else "HEAD", "--stat", "--patch")
    data: dict[str, Any] = {
        "repo": name,
        "branch": branch,
        "files": files,
        "staged_only": bool(staged),
        "diff": diff[:MAX_DIFF_CHARS],
        "diff_truncated": len(diff) > MAX_DIFF_CHARS,
    }
    if not files:
        return ToolResult.success(data=data, speech=f"Nothing has changed in {name} on {branch}.")
    count = len(staged) if staged else len(files)
    which = ("staged" if staged else "changed") + (" file" if count == 1 else " files")
    speech = f"{count} {which} in {name} on {branch}."
    return ToolResult.success(data=hide_secrets(data, "diff"), speech=speech)


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, timeout_s=60)
async def git_commit(ctx: ToolContext, repo: str, message: str) -> ToolResult:
    """Commit the changes in one of the user's git repositories, after asking. Commits what is
    staged, or every change when nothing is staged. Write the message from git_changes.

    Args:
        repo: The repository name, for example "jarvis".
        message: The commit message: a short summary line, optionally a blank line and details.
    """
    name, folder = choose_repo(ctx, repo)
    staged = (await run_git(folder, "diff", "--cached", "--name-only")).split()
    if not staged:
        await run_git(folder, "add", "--all")
    await run_git(folder, "commit", "--message", message)
    commit = (await run_git(folder, "rev-parse", "--short", "HEAD")).strip()
    branch = await current_branch(folder)
    return ToolResult.success(
        data={"repo": name, "branch": branch, "commit": commit, "message": message},
        speech=f"Committed to {branch} in {name}.",
    )


def _files(count: int) -> str:
    return f"{count} file" if count == 1 else f"{count} files"


@git_commit.preparer
async def _prepare_commit(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    name, folder = choose_repo(ctx, str(args["repo"]))
    message = "\n".join(line.rstrip() for line in str(args["message"]).strip().splitlines())
    if not message:
        raise ToolError("Write a commit message from git_changes first.")
    if len(message) > MAX_MESSAGE_CHARS:
        raise ToolError(f"Keep the commit message under {MAX_MESSAGE_CHARS} characters.")
    branch = await current_branch(folder)
    staged = (await run_git(folder, "diff", "--cached", "--name-only")).split()
    files = staged or changed_files(await run_git(folder, "status", "--porcelain=v1"))
    if not files:
        raise ToolError(f"Nothing has changed in {name}, so there is nothing to commit.")
    shown = ", ".join(files[:4]) + (f" and {len(files) - 4} more" if len(files) > 4 else "")
    first_line = message.splitlines()[0]
    return Prepared(
        args={"repo": name, "message": message},
        summary=f'Commit {_files(len(files))} to {branch} in {name}: "{first_line}"',
        risk=Risk.CONFIRM,
        reason=f"{'staged' if staged else 'all changes'}: {shown}",
    )


@tool(risk=Risk.CONFIRM, sensitivity=Sensitivity.PRIVATE, egress=True, timeout_s=120)
async def git_push(ctx: ToolContext, repo: str) -> ToolResult:
    """Push the current branch of one of the user's git repositories to its remote, after
    asking. Never forces.

    Args:
        repo: The repository name, for example "jarvis".
    """
    name, folder = choose_repo(ctx, repo)
    branch = await current_branch(folder)
    remote = ctx.settings.git.remote
    upstream = await _upstream(folder)
    args = ["push", remote, branch] if upstream else ["push", "--set-upstream", remote, branch]
    await run_git(folder, *args, timeout_s=110)
    return ToolResult.success(
        data={"repo": name, "branch": branch, "remote": remote},
        speech=f"Pushed {branch} to {remote}.",
    )


async def _upstream(folder: Path) -> str | None:
    try:
        return (await run_git(folder, "rev-parse", "--abbrev-ref", "@{upstream}")).strip() or None
    except ToolError:
        return None


@git_push.preparer
async def _prepare_push(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    name, folder = choose_repo(ctx, str(args["repo"]))
    branch = await current_branch(folder)
    if not _BRANCH.match(branch):
        raise ToolError(f"'{branch}' is not a branch name I can push.")
    remote = ctx.settings.git.remote
    remotes = (await run_git(folder, "remote")).split()
    if remote not in remotes:
        raise ToolError(f"{name} has no remote called {remote}.")
    upstream = await _upstream(folder)
    if upstream:
        ahead = int(
            (await run_git(folder, "rev-list", "--count", f"{upstream}..HEAD")).strip() or 0
        )
        if ahead == 0:
            raise ToolError(f"{branch} in {name} has nothing new to push.")
        count = f"{ahead} commit{'s' if ahead != 1 else ''}"
    else:
        count = "a new branch"
    reasons = [f"it publishes {count} to {remote}"]
    if branch in MAIN_BRANCHES:
        reasons.append(f"{branch} is the main branch")
    return Prepared(
        args={"repo": name},
        summary=f"Push {branch} of {name} to {remote} ({count})",
        risk=Risk.CONFIRM,
        reason="; ".join(reasons),
    )
