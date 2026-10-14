"""Shared fakes and fixtures. Tests never call Ollama, launch apps, speak, or hit the network."""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

from jarvis.app import App, build_app
from jarvis.config import Settings, load_settings
from jarvis.core.channel import ConfirmationRequest
from jarvis.llm.types import LLMReply, ToolCall
from jarvis.platform.windows import WindowInfo
from jarvis.services import Services
from jarvis.storage.db import Database
from jarvis.tools.apps.index import AppEntry, AppIndex
from jarvis.tools.files.guard import FileGuard
from jarvis.tools.files.index import FileIndex
from jarvis.tools.registry import Registry
from jarvis.tools.web.search import SearchHit

REPO = Path(__file__).resolve().parents[1]
_ids = itertools.count(1)


class Hang:
    """A scripted LLM step that never returns (until cancelled)."""


def reply(text: str = "", *calls: tuple[str, dict[str, Any] | str]) -> LLMReply:
    tool_calls = [
        ToolCall(
            id=f"call_{next(_ids)}",
            name=name,
            arguments=args if isinstance(args, str) else json.dumps(args),
        )
        for name, args in calls
    ]
    return LLMReply(text=text, model="fake-model", latency_ms=1, tool_calls=tool_calls)


class FakeLLM:
    def __init__(self, script: Sequence[LLMReply | BaseException | Hang]) -> None:
        self._script = list(script)
        self.requests: list[list[dict[str, Any]]] = []
        self.tools_seen: list[list[dict[str, Any]] | None] = []

    @property
    def model(self) -> str:
        return "fake-model"

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None = None
    ) -> LLMReply:
        self.requests.append([dict(m) for m in messages])
        self.tools_seen.append(tools)
        step = self._script.pop(0) if self._script else reply("Done.")
        if isinstance(step, Hang):
            await asyncio.sleep(3600)
        if isinstance(step, BaseException):
            raise step
        assert isinstance(step, LLMReply)
        return step

    async def check(self) -> str | None:
        return None

    async def aclose(self) -> None:
        return None


class FakeChannel:
    name = "test"

    def __init__(self, confirm: bool | None = True, answers: Sequence[str] = ()) -> None:
        self._confirm = confirm  # None means never answer
        self._answers = list(answers)
        self.requests: list[ConfirmationRequest] = []
        self.questions: list[tuple[str, Sequence[str] | None]] = []

    async def confirm(self, request: ConfirmationRequest) -> bool:
        self.requests.append(request)
        if self._confirm is None:
            await asyncio.Event().wait()
        return bool(self._confirm)

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        self.questions.append((question, options))
        return self._answers.pop(0) if self._answers else ""


class FakeTTS:
    def __init__(self) -> None:
        self.spoken: list[str] = []

    async def speak(self, text: str) -> None:
        self.spoken.append(text)

    async def stop(self) -> None:
        return None


class FakeSearch:
    def __init__(self, hits: list[SearchHit] | None = None) -> None:
        self.hits = hits if hits is not None else [SearchHit("Python", "https://python.org", "x")]
        self.queries: list[str] = []

    async def search(self, query: str, max_results: int) -> list[SearchHit]:
        self.queries.append(query)
        return self.hits[:max_results]


def fake_apps(
    *names: str,
    aliases: dict[str, str] | None = None,
    process_names: dict[str, str] | None = None,
) -> AppIndex:
    entries = [AppEntry(name=n, target=f"App.{n}", kind="appsfolder") for n in names]
    return AppIndex(
        sources=[lambda: entries],
        aliases=aliases or {},
        process_names=process_names or {},
        threshold=75,
    )


DEFAULT_APPS = ("Notepad", "Visual Studio Code", "Spotify", "Calculator")


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return load_settings(
        REPO / "config",
        include_local=False,
        env_file=tmp_path / "missing.env",
        overrides={"data_dir": str(tmp_path)},
    )


@pytest.fixture(autouse=True)
def launched(monkeypatch: pytest.MonkeyPatch) -> list[AppEntry]:
    """Record app launches instead of starting real apps."""
    calls: list[AppEntry] = []
    monkeypatch.setattr("jarvis.tools.apps.tools.launch", calls.append)
    return calls


class FakeDesktop:
    """Stands in for real windows, file opening, the browser, and VS Code in every test."""

    def __init__(self) -> None:
        self.windows: list[WindowInfo] = []
        self.focused: list[int] = []
        self.closed: list[int] = []
        self.opened_files: list[str] = []
        self.urls: list[str] = []
        self.spawned: list[list[str]] = []

    def add(self, title: str, exe: str, class_name: str = "Window") -> WindowInfo:
        window = WindowInfo(1000 + len(self.windows), title, 1, exe, class_name)
        self.windows.append(window)
        return window

    def close(self, hwnd: int) -> None:
        self.closed.append(hwnd)
        self.windows = [w for w in self.windows if w.hwnd != hwnd]


@pytest.fixture(autouse=True)
def desktop(monkeypatch: pytest.MonkeyPatch) -> FakeDesktop:
    fake = FakeDesktop()
    monkeypatch.setattr("jarvis.platform.windows.list_windows", lambda: list(fake.windows))
    monkeypatch.setattr(
        "jarvis.platform.windows.focus_window", lambda hwnd: fake.focused.append(hwnd) or True
    )
    monkeypatch.setattr("jarvis.platform.windows.close_window", fake.close)
    monkeypatch.setattr("os.startfile", fake.opened_files.append, raising=False)
    monkeypatch.setattr("webbrowser.open", lambda url: fake.urls.append(url) or True)
    monkeypatch.setattr("jarvis.tools.apps.vscode.spawn", fake.spawned.append)
    return fake


class Harness:
    def __init__(self, app: App, llm: FakeLLM, channel: FakeChannel, tts: FakeTTS) -> None:
        self.app = app
        self.llm = llm
        self.channel = channel
        self.tts = tts
        self.files_root = Path()
        self.events: list[Any] = []
        app.bus.subscribe(self.events.append)

    def audit(self) -> list[dict[str, Any]]:
        return self.app.audit.recent(100)


MakeApp = Callable[..., Harness]


@pytest.fixture
def make_app(settings: Settings) -> MakeApp:
    def factory(
        script: Sequence[LLMReply | BaseException | Hang] = (),
        *,
        channel: FakeChannel | None = None,
        search: FakeSearch | None = None,
        registry: Registry | None = None,
        overrides: dict[str, Any] | None = None,
    ) -> Harness:
        cfg = settings
        if overrides:
            cfg = load_settings(
                REPO / "config",
                include_local=False,
                env_file=settings.data_dir / "missing.env",
                overrides={"data_dir": str(settings.data_dir), **overrides},
            )
        llm = FakeLLM(script)
        tts = FakeTTS()
        chan = channel or FakeChannel()
        db = Database(":memory:")
        files_root = (cfg.data_dir / "files").resolve()
        files_root.mkdir(exist_ok=True)
        services = Services(
            tts=tts,
            apps=fake_apps(
                *DEFAULT_APPS, aliases=cfg.apps.aliases, process_names=cfg.apps.process_names
            ),
            files=FileIndex(db, FileGuard(cfg.files, roots=[files_root]), cfg.files),
            search=search or FakeSearch(),
        )
        app = build_app(cfg, chan, llm=llm, services=services, registry=registry, db=db)
        harness = Harness(app, llm, chan, tts)
        harness.files_root = files_root
        return harness

    return factory
