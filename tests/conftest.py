"""Shared fakes and fixtures. Tests never call Ollama, launch apps, speak, or hit the network."""

from __future__ import annotations

import asyncio
import itertools
import json
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis.app import App, build_app
from jarvis.config import Settings, load_settings
from jarvis.core.channel import ConfirmationRequest
from jarvis.llm.types import LLMReply, ToolCall
from jarvis.platform.windows import WindowInfo
from jarvis.services import Services
from jarvis.storage.db import Database
from jarvis.tools.apps.index import AppEntry, AppIndex
from jarvis.tools.data.http import ApiClient, ProviderError
from jarvis.tools.data.hub import DataHub
from jarvis.tools.data.market import Listing, Price
from jarvis.tools.files.guard import FileGuard
from jarvis.tools.files.index import FileIndex
from jarvis.tools.registry import Registry
from jarvis.tools.system.reminders import Reminders
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


class FakeWeb:
    """Canned HTTP answers by URL prefix. Anything else fails the way a dead network does."""

    def __init__(self) -> None:
        self.routes: dict[str, Callable[[httpx.Request], httpx.Response]] = {}
        self.requests: list[httpx.Request] = []
        self.dns: dict[str, list[str]] = {"localhost": ["127.0.0.1"]}

    def route(
        self,
        prefix: str,
        json: Any = None,
        *,
        status: int = 200,
        content: bytes | str | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        """Answer requests whose host and path start with `prefix`, e.g. "api.example.com/v1"."""

        def answer(request: httpx.Request) -> httpx.Response:
            if json is not None:
                return httpx.Response(status, json=json, headers=headers)
            return httpx.Response(status, content=content or b"", headers=headers)

        self.routes[prefix] = answer

    def handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        target = f"{request.url.host}{request.url.path}"
        for prefix, answer in self.routes.items():
            if target.startswith(prefix):
                return answer(request)
        raise httpx.ConnectError("no network in tests", request=request)

    def hits(self, prefix: str) -> int:
        return sum(f"{r.url.host}{r.url.path}".startswith(prefix) for r in self.requests)

    async def addresses(self, host: str, port: int) -> list[str]:
        return self.dns.get(host, ["93.184.216.34"])


class FakeYahoo:
    """Stands in for yfinance: symbol search and quotes from dictionaries."""

    name = "yfinance"

    def __init__(self) -> None:
        self.listings: dict[str, list[Listing]] = {}
        self.prices: dict[str, Price] = {}
        self.offline = False
        self.broken = False  # fails with an error that does not say whether the network is down
        self.searches: list[str] = []
        self.quotes: list[str] = []

    def supports(self, symbol: str) -> bool:
        return True

    async def price(self, api: ApiClient, symbol: str) -> Price:
        async def request() -> Price:
            self.quotes.append(symbol)
            if self.offline:
                raise ProviderError(self.name, "could not connect", offline=True)
            if self.broken:
                raise ProviderError(self.name, "failed (KeyError)")
            if symbol not in self.prices:
                raise ProviderError(self.name, f"no price for {symbol}", miss=True)
            return self.prices[symbol]

        return await api.call(self.name, request)

    async def search(self, api: ApiClient, query: str) -> list[Listing]:
        async def request() -> list[Listing]:
            self.searches.append(query)
            if self.offline:
                raise ProviderError(self.name, "could not connect", offline=True)
            return self.listings.get(query.casefold(), [])

        return await api.call(self.name, request)


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
    """Stands in for windows, files, the browser, VS Code, and system controls in every test."""

    def __init__(self) -> None:
        self.windows: list[WindowInfo] = []
        self.focused: list[int] = []
        self.closed: list[int] = []
        self.opened_files: list[str] = []
        self.urls: list[str] = []
        self.spawned: list[list[str]] = []
        self.volume = 40
        self.muted = False
        self.brightness: int | None = 50  # None: no built-in screen
        self.locked = 0
        self.screenshots: list[Path] = []
        self.clipboard: str | None = None

    def add(self, title: str, exe: str, class_name: str = "Window") -> WindowInfo:
        window = WindowInfo(1000 + len(self.windows), title, 1, exe, class_name)
        self.windows.append(window)
        return window

    def close(self, hwnd: int) -> None:
        self.closed.append(hwnd)
        self.windows = [w for w in self.windows if w.hwnd != hwnd]

    def set_volume(self, level: int | None = None, mute: bool | None = None) -> tuple[int, bool]:
        if level is not None:
            self.volume = level
        if mute is not None:
            self.muted = mute
        return self.volume, self.muted

    def get_brightness(self) -> int:
        if self.brightness is None:
            raise OSError("no WmiMonitorBrightness instance")
        return self.brightness

    def set_brightness(self, level: int) -> int:
        self.get_brightness()
        self.brightness = level
        return level

    def lock(self) -> None:
        self.locked += 1

    def capture(self, path: Path) -> tuple[int, int]:
        self.screenshots.append(path)
        return 1920, 1080

    def set_clipboard(self, text: str) -> None:
        self.clipboard = text


async def _run_inline(fn: Callable[..., Any], *args: Any) -> Any:
    return fn(*args)


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
    monkeypatch.setattr("jarvis.tools.system.controls.run_com", _run_inline)
    monkeypatch.setattr("jarvis.platform.volume.get_volume", lambda: (fake.volume, fake.muted))
    monkeypatch.setattr("jarvis.platform.volume.set_volume", fake.set_volume)
    monkeypatch.setattr("jarvis.platform.display.get_brightness", fake.get_brightness)
    monkeypatch.setattr("jarvis.platform.display.set_brightness", fake.set_brightness)
    monkeypatch.setattr("jarvis.platform.display.lock_workstation", fake.lock)
    monkeypatch.setattr("jarvis.platform.display.capture_screen", fake.capture)
    monkeypatch.setattr("jarvis.platform.clipboard.get_text", lambda: fake.clipboard)
    monkeypatch.setattr("jarvis.platform.clipboard.set_text", fake.set_clipboard)
    return fake


@pytest.fixture(autouse=True)
def web(monkeypatch: pytest.MonkeyPatch) -> FakeWeb:
    fake = FakeWeb()
    monkeypatch.setattr("jarvis.tools.web.fetch.addresses", fake.addresses)
    return fake


@pytest.fixture
def yahoo() -> FakeYahoo:
    return FakeYahoo()


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
def make_app(settings: Settings, web: FakeWeb, yahoo: FakeYahoo) -> MakeApp:
    def factory(
        script: Sequence[LLMReply | BaseException | Hang] = (),
        *,
        channel: FakeChannel | None = None,
        search: FakeSearch | None = None,
        registry: Registry | None = None,
        overrides: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
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
            data=DataHub(
                db,
                cfg,
                http=httpx.AsyncClient(transport=httpx.MockTransport(web.handle)),
                yahoo=yahoo,
                env=env or {},
            ),
            reminders=Reminders(db),
        )
        app = build_app(cfg, chan, llm=llm, services=services, registry=registry, db=db)
        harness = Harness(app, llm, chan, tts)
        harness.files_root = files_root
        return harness

    return factory
