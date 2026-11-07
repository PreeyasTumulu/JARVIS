"""Phase 27: Spotify, Docker with readiness, SSH profiles, git, and timing arguments."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from jarvis.llm.types import ToolCall
from jarvis.platform.media import MediaState
from jarvis.tools import registry as registry_module
from jarvis.tools.apps import docker_up as up
from jarvis.tools.base import ToolContext
from jarvis.tools.dev import ssh
from jarvis.tools.media import spotify
from tests.conftest import FakeChannel, FakeDesktop, FakeWeb, Harness, MakeApp

KEYS = {"SPOTIFY_CLIENT_ID": "id", "SPOTIFY_CLIENT_SECRET": "secret"}


def context(h: Harness) -> ToolContext:
    return ToolContext(h.app.settings, h.channel, h.app.services, "s", "t")


async def call(h: Harness, tool: str, **args: Any) -> Any:
    return await h.app.agent.executor.run(ToolCall("c1", tool, json.dumps(args)), context(h))


# Timing arguments on tools that only run now


async def test_open_app_at_a_time_is_refused_not_run_now(make_app: MakeApp, launched: list) -> None:
    h = make_app()
    outcome = await call(h, "open_app", name="vs code", at="tomorrow 9")
    assert outcome.decision == "invalid"
    assert "schedule_app" in outcome.result.error
    assert launched == []


def test_tools_that_take_a_time_still_accept_it() -> None:
    from jarvis.tools.catalog import build_registry

    tools = build_registry()
    schedule = tools.get("schedule_app")
    reminder = tools.get("set_reminder")
    assert schedule is not None
    assert reminder is not None
    assert schedule.validate({"action": "open", "name": "x", "at": "9 am"})["at"] == "9 am"
    assert reminder.validate({"message": "tea", "at": "5 pm"})["at"] == "5 pm"
    assert "at" in registry_module.LATER_WORDS


# Spotify


class Player:
    def __init__(self) -> None:
        self.states: list[MediaState | None] = []
        self.plays = 0

    async def app_state(self, app: str) -> MediaState | None:
        return self.states.pop(0) if len(self.states) > 1 else (self.states or [None])[0]

    async def play_app(self, app: str) -> bool:
        self.plays += 1
        return True


@pytest.fixture
def player(monkeypatch: pytest.MonkeyPatch) -> Player:
    fake = Player()
    monkeypatch.setattr(spotify.media, "app_state", fake.app_state)
    monkeypatch.setattr(spotify.media, "play_app", fake.play_app)
    monkeypatch.setattr(spotify, "_token", None)
    monkeypatch.setattr(spotify, "SESSION_WAIT_S", 0.2)
    monkeypatch.setattr(spotify, "PLAYING_WAIT_S", 0.5)
    return fake


def spotify_api(web: FakeWeb, results: dict[str, Any], *, token_status: int = 200) -> None:
    web.route(
        "accounts.spotify.com/api/token",
        {"access_token": "tok", "expires_in": 3600},
        status=token_status,
    )
    web.route("api.spotify.com/v1/search", results)


TRACK = {
    "tracks": {
        "items": [
            {
                "name": "Snowman",
                "uri": "spotify:track:abc",
                "artists": [{"name": "WYS"}],
            }
        ]
    }
}


async def test_a_track_is_found_opened_and_checked(
    make_app: MakeApp, web: FakeWeb, desktop: FakeDesktop, player: Player
) -> None:
    spotify_api(web, TRACK)
    player.states = [
        None,
        MediaState("Spotify", "paused"),
        MediaState("Spotify", "playing", "Snowman", "WYS"),
    ]
    h = make_app(env=KEYS)
    outcome = await call(h, "play_spotify", query="play snowman by wys on spotify")
    assert outcome.result.speech == "Playing Snowman by WYS on Spotify."
    assert desktop.opened_files == ["spotify:track:abc"]
    assert player.plays == 1
    search = next(r for r in web.requests if "v1/search" in str(r.url))
    assert search.url.params["q"] == "snowman by wys"
    assert search.url.params["type"] == "track"
    assert search.url.params["market"] == "IN"
    assert search.headers["authorization"] == "Bearer tok"


async def test_when_spotify_plays_something_else_it_says_so(
    make_app: MakeApp, web: FakeWeb, player: Player
) -> None:
    spotify_api(web, TRACK)
    player.states = [MediaState("Spotify", "playing", "Old song", "Someone")]
    h = make_app(env=KEYS)
    outcome = await call(h, "play_spotify", query="snowman")
    assert outcome.result.speech == (
        "I opened Snowman by WYS in Spotify. If it isn't playing yet, press play on it."
    )
    assert outcome.result.data["playing"] is False


async def test_a_playlist_from_the_words(make_app: MakeApp, web: FakeWeb, player: Player) -> None:
    playlist = {
        "playlists": {
            "items": [
                None,
                {
                    "name": "Lofi Beats",
                    "uri": "spotify:playlist:p1",
                    "owner": {"display_name": "Spotify"},
                },
            ]
        }
    }
    spotify_api(web, playlist)
    player.states = [None, MediaState("Spotify", "playing", "Track one", "Artist")]
    h = make_app(env=KEYS)
    outcome = await call(h, "play_spotify", query="play the lofi beats playlist")
    assert outcome.result.data["kind"] == "playlist"
    assert outcome.result.speech == "Playing Lofi Beats by Spotify on Spotify."


async def test_without_keys_spotify_s_search_opens(
    make_app: MakeApp, desktop: FakeDesktop, player: Player
) -> None:
    h = make_app()
    outcome = await call(h, "play_spotify", query="lofi beats")
    assert desktop.opened_files == ["spotify:search:lofi%20beats"]
    assert "SPOTIFY_CLIENT_ID" in outcome.result.speech


async def test_refused_keys_are_reported(make_app: MakeApp, web: FakeWeb, player: Player) -> None:
    spotify_api(web, TRACK, token_status=401)
    h = make_app(env=KEYS)
    outcome = await call(h, "play_spotify", query="snowman")
    assert not outcome.result.ok
    assert "refused" in outcome.result.error


def test_spotify_words() -> None:
    assert spotify.clean_query("play the album Discovery on Spotify") == "Discovery"
    assert spotify.wanted_kind("the album Discovery", "auto") == "album"
    assert spotify.wanted_kind("that song by Adele", "auto") == "track"
    assert spotify.wanted_kind("anything", "artist") == "artist"


# Docker


class FakeDocker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ...]] = []
        self.states: dict[str, list[dict[str, Any]]] = {}
        self.ports: dict[str, str] = {}
        self.compose_ps = ""

    async def run(self, *args: str, timeout_s: float = 20) -> str:
        self.calls.append(args)
        if args[0] == "run":
            return "f00dfeed\n"
        if args[0] == "inspect":
            queue = self.states[args[-1]]
            return json.dumps(queue.pop(0) if len(queue) > 1 else queue[0])
        if args[0] == "port":
            return self.ports.get(args[-1], "")
        if args[0] == "logs":
            return "fatal: password=hunter2 is wrong\n"
        if args[:1] == ("compose",) and "ps" in args:
            return self.compose_ps
        return ""


@pytest.fixture
def docker(monkeypatch: pytest.MonkeyPatch) -> FakeDocker:
    fake = FakeDocker()
    monkeypatch.setattr(up, "run_docker", fake.run)
    monkeypatch.setattr(up, "POLL_S", 0)

    async def answers(port: int) -> bool:
        return True

    monkeypatch.setattr(up, "port_answers", answers)
    return fake


async def test_an_image_asks_runs_and_waits_for_health(
    make_app: MakeApp, docker: FakeDocker
) -> None:
    docker.states["redis"] = [
        {"Running": True, "Health": {"Status": "starting"}},
        {"Running": True, "Health": {"Status": "healthy"}},
    ]
    h = make_app()
    outcome = await call(h, "docker_up", target="Redis:7", ports=["6379"], name="redis")
    (request,) = h.channel.requests
    assert request.summary == "Run the image redis:7 as redis, ports 6379:6379"
    assert outcome.result.speech == "redis is ready."
    assert docker.calls[0] == ("run", "-d", "--name", "redis", "-p", "6379:6379", "redis:7")


async def test_ports_must_answer_without_a_health_check(
    make_app: MakeApp, docker: FakeDocker
) -> None:
    docker.states["web"] = [{"Running": True}]
    docker.ports["web"] = "80/tcp -> 0.0.0.0:8080\n80/tcp -> [::]:8080\n"
    h = make_app()
    outcome = await call(h, "docker_up", target="nginx", ports=["8080:80"], name="web")
    assert outcome.result.ok
    assert outcome.result.data["containers"][0]["detail"] == "port 8080 answers"


async def test_a_container_that_stops_is_reported_with_its_log(
    make_app: MakeApp, docker: FakeDocker
) -> None:
    docker.states["db"] = [{"Running": False, "Status": "exited", "ExitCode": 1}]
    h = make_app()
    outcome = await call(h, "docker_up", target="postgres:16", name="db")
    assert "db is stopped (exited, exit code 1)" in outcome.result.speech
    assert "hunter2" not in outcome.result.data["logs"]


async def test_a_compose_project_from_config(
    make_app: MakeApp, docker: FakeDocker, tmp_path: Path
) -> None:
    folder = tmp_path / "shop"
    folder.mkdir()
    docker.compose_ps = '{"Name": "shop-api-1"}\n{"Name": "shop-db-1"}\n'
    docker.states["shop-api-1"] = [{"Running": True}]
    docker.states["shop-db-1"] = [{"Running": True, "Health": {"Status": "healthy"}}]
    h = make_app(overrides={"docker": {"projects": {"shop": {"path": str(folder)}}}})
    outcome = await call(h, "docker_up", target="the shop project")
    assert (
        h.channel.requests[0].summary == f"Start the shop project (docker compose up in {folder})"
    )
    assert outcome.result.speech == "The shop project is ready."
    assert ("compose", "--project-directory", str(folder), "up", "-d") in docker.calls


@pytest.mark.parametrize("bad", ["redis; rm -rf /", "--privileged", "UPPER CASE", "a" * 300])
async def test_only_image_names_can_be_run(make_app: MakeApp, docker: FakeDocker, bad: str) -> None:
    h = make_app()
    outcome = await call(h, "docker_up", target=bad)
    assert not outcome.result.ok
    assert docker.calls == []


async def test_bad_ports_and_names_are_refused(make_app: MakeApp, docker: FakeDocker) -> None:
    h = make_app()
    assert not (await call(h, "docker_up", target="redis", ports=["99999:1"])).result.ok
    assert not (await call(h, "docker_up", target="redis", name="-x")).result.ok
    assert docker.calls == []


def test_published_ports() -> None:
    assert up.published_ports("6379/tcp -> 0.0.0.0:6379\n6379/tcp -> [::]:6379\n") == [6379]
    assert up.published_ports("") == []


# SSH


@pytest.fixture
def spawned(monkeypatch: pytest.MonkeyPatch) -> list[list[str]]:
    calls: list[list[str]] = []
    monkeypatch.setattr(ssh, "spawn", calls.append)
    monkeypatch.setattr(ssh.shutil, "which", lambda name: "C:/wt.exe" if name == "wt" else None)
    return calls


async def test_a_profile_opens_a_terminal(make_app: MakeApp, spawned: list) -> None:
    profiles = {"pi": {"host": "192.168.1.20", "user": "me", "port": 2222}}
    h = make_app(overrides={"ssh": {"profiles": profiles}})
    outcome = await call(h, "ssh_connect", profile="my raspberry pi")
    assert outcome.result.speech == "Opening an SSH session to pi."
    assert spawned == [
        ["C:/wt.exe", "new-tab", "--title", "pi", "ssh", "-p", "2222", "me@192.168.1.20"]
    ]


async def test_without_windows_terminal_a_console_opens(
    make_app: MakeApp, spawned: list, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ssh.shutil, "which", lambda name: None)
    h = make_app(overrides={"ssh": {"profiles": {"server": {"host": "example.com"}}}})
    await call(h, "ssh_connect", profile="server")
    assert spawned[0][:3] == ["cmd.exe", "/c", "start"]
    assert spawned[0][-1] == "example.com"


async def test_bad_profiles_never_reach_ssh(make_app: MakeApp, spawned: list) -> None:
    h = make_app(overrides={"ssh": {"profiles": {"x": {"host": "-oProxyCommand=calc"}}}})
    assert not (await call(h, "ssh_connect", profile="x")).result.ok
    none = make_app()
    missing = await call(none, "ssh_connect", profile="server")
    assert "No SSH profiles" in missing.result.error
    assert spawned == []


# Git, in a real repository with a local remote


def git(folder: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(folder), *args], check=True, capture_output=True, text=True
    ).stdout


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    remote = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--bare", "-q", str(remote)], check=True)
    folder = tmp_path / "shop"
    folder.mkdir()
    git(folder, "init", "-q", "-b", "main")
    git(folder, "config", "user.email", "test@example.com")
    git(folder, "config", "user.name", "Test")
    (folder / "app.py").write_text("print('hi')\n", "utf-8")
    git(folder, "add", "-A")
    git(folder, "commit", "-q", "-m", "first")
    git(folder, "remote", "add", "origin", str(remote))
    git(folder, "push", "-q", "-u", "origin", "main")
    return folder


@pytest.fixture
def git_app(make_app: MakeApp, repo: Path) -> Harness:
    return make_app(overrides={"git": {"repos": {"shop": str(repo)}}})


async def test_changes_then_a_commit_after_a_yes(git_app: Harness, repo: Path) -> None:
    (repo / "app.py").write_text("print('hello')\n", "utf-8")
    (repo / "new.txt").write_text("x\n", "utf-8")
    changes = await call(git_app, "git_changes", repo="my shop repo")
    assert changes.result.data["files"] == ["app.py", "new.txt"]
    assert "print('hello')" in changes.result.data["diff"]
    assert changes.tool.untrusted
    commit = await call(
        git_app, "git_commit", repo="shop", message="Say hello\n\nGreets more warmly."
    )
    (request,) = git_app.channel.requests
    assert request.summary == 'Commit 2 files to main in shop: "Say hello"'
    assert commit.result.speech == "Committed to main in shop."
    assert git(repo, "log", "-1", "--format=%B").strip() == "Say hello\n\nGreets more warmly."
    assert git(repo, "status", "--porcelain") == ""


async def test_only_what_is_staged_is_committed(git_app: Harness, repo: Path) -> None:
    (repo / "app.py").write_text("print('staged')\n", "utf-8")
    (repo / "other.txt").write_text("not staged\n", "utf-8")
    git(repo, "add", "app.py")
    await call(git_app, "git_commit", repo="shop", message="Staged only")
    assert "other.txt" in git(repo, "status", "--porcelain")


async def test_a_no_commits_nothing(make_app: MakeApp, repo: Path) -> None:
    h = make_app(
        channel=FakeChannel(confirm=False), overrides={"git": {"repos": {"shop": str(repo)}}}
    )
    (repo / "app.py").write_text("changed\n", "utf-8")
    await call(h, "git_commit", repo="shop", message="Nope")
    assert git(repo, "log", "--oneline").count("\n") == 1


async def test_push_asks_with_the_count_and_never_forces(git_app: Harness, repo: Path) -> None:
    (repo / "app.py").write_text("v2\n", "utf-8")
    git(repo, "commit", "-qam", "v2")
    outcome = await call(git_app, "git_push", repo="shop")
    (request,) = git_app.channel.requests
    assert request.summary == "Push main of shop to origin (1 commit)"
    assert "main branch" in (request.reason or "")
    assert outcome.result.speech == "Pushed main to origin."
    assert git(repo, "status", "-sb").startswith("## main...origin/main\n")
    nothing = await call(git_app, "git_push", repo="shop")
    assert "nothing new to push" in nothing.result.error


async def test_a_new_branch_is_pushed_with_an_upstream(git_app: Harness, repo: Path) -> None:
    git(repo, "switch", "-q", "-c", "feature/login")
    (repo / "login.py").write_text("x\n", "utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "login")
    await call(git_app, "git_push", repo="shop")
    assert (
        git_app.channel.requests[0].summary == "Push feature/login of shop to origin (a new branch)"
    )
    assert "origin/feature/login" in git(repo, "branch", "-vv")


async def test_unknown_repos_and_no_config(make_app: MakeApp, git_app: Harness) -> None:
    assert "Repositories: shop" in (await call(git_app, "git_changes", repo="blog")).result.error
    assert "No git repositories" in (await call(make_app(), "git_changes", repo="x")).result.error
