"""Shared fakes and fixtures. Tests never call Ollama, launch apps, speak, or hit the network."""

from __future__ import annotations

import asyncio
import ipaddress
import itertools
import json
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx
import pytest

from jarvis.app import App, build_app
from jarvis.config import Settings, load_settings
from jarvis.core.channel import ConfirmationRequest
from jarvis.llm.router import Router
from jarvis.llm.types import LLMReply, ToolCall
from jarvis.platform.notifications import NotificationAccessError, RawNotification
from jarvis.platform.uia import Control, WindowContent
from jarvis.platform.windows import WindowInfo
from jarvis.services import Services
from jarvis.storage.db import Database
from jarvis.tools.apps.index import AppEntry, AppIndex
from jarvis.tools.browser.session import PageElement, PageSnapshot
from jarvis.tools.data.http import ApiClient, ProviderError
from jarvis.tools.data.hub import DataHub
from jarvis.tools.data.market import Listing, Price
from jarvis.tools.files.guard import FileGuard
from jarvis.tools.files.index import FileIndex
from jarvis.tools.memory import MemoryStore
from jarvis.tools.messaging.contacts import ContactBook
from jarvis.tools.messaging.whatsapp import SendStatus, Sent
from jarvis.tools.notifications.store import Notifications
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
        try:
            return [str(ipaddress.ip_address(host))]  # an address resolves to itself
        except ValueError:
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
        # UI automation: per window, its controls and text; what was typed, pressed, clicked.
        self.foreground = 0
        self.refuse_focus = False
        self.elevated: set[int] = set()  # process ids running as administrator
        self.controls: dict[int, list[Control]] = {}
        self.lines: dict[int, list[str]] = {}
        self.field: dict[int, Control | None] = {}  # the focused control per window
        self.typed: list[str] = []
        self.keys: list[tuple[tuple[int, ...], int]] = []
        self.pressed: list[str] = []
        self.steal_focus_after: int | None = None  # chunks typed before another window takes over
        self.app_text: str | None = None  # what the focused field shows; None: what was typed

    def add(self, title: str, exe: str, class_name: str = "Window", pid: int = 1) -> WindowInfo:
        window = WindowInfo(1000 + len(self.windows), title, pid, exe, class_name)
        self.windows.append(window)
        return window

    def focus(self, hwnd: int) -> bool:
        self.focused.append(hwnd)
        if self.refuse_focus:
            return False
        self.foreground = hwnd
        return True

    def read_window(
        self, hwnd: int, max_chars: int, visible_only: bool = True
    ) -> tuple[WindowContent, bool]:
        lines = self.lines.get(hwnd, [])
        return WindowContent(list(lines), list(self.controls.get(hwnd, []))), False

    def focus_field(self, hwnd: int, field: Control | None = None) -> Control:
        from jarvis.platform.uia import UIAError

        if field is None:
            field = self.field.get(hwnd) or next(
                (c for c in self.controls.get(hwnd, []) if c.kind in ("field", "document")), None
            )
        if field is None:
            raise UIAError("I can't find a place to type in that window.")
        self.field[hwnd] = field
        return field

    def press(self, hwnd: int, control: Control) -> str:
        self.pressed.append(control.name)
        return "pressed"

    def type_unicode(self, text: str) -> None:
        self.typed.append(text)
        if self.steal_focus_after is not None and len(self.typed) >= self.steal_focus_after:
            self.foreground = 1

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
    monkeypatch.setattr("jarvis.platform.windows.focus_window", fake.focus)
    monkeypatch.setattr("jarvis.platform.windows.foreground_window", lambda: fake.foreground)
    monkeypatch.setattr("jarvis.platform.windows.is_minimized", lambda hwnd: False)
    monkeypatch.setattr("jarvis.platform.uia.read_window", fake.read_window)
    monkeypatch.setattr("jarvis.platform.uia.focus_field", fake.focus_field)
    monkeypatch.setattr("jarvis.platform.uia.focused_control", lambda hwnd: fake.field.get(hwnd))
    monkeypatch.setattr("jarvis.platform.uia.press", fake.press)
    monkeypatch.setattr(
        "jarvis.platform.uia.focused_text",
        lambda hwnd: "".join(fake.typed) if fake.app_text is None else fake.app_text,
    )
    monkeypatch.setattr("jarvis.platform.sendinput.type_unicode", fake.type_unicode)
    monkeypatch.setattr(
        "jarvis.platform.sendinput.press_combo",
        lambda mods, vk: fake.keys.append((tuple(mods), vk)),
    )
    monkeypatch.setattr("jarvis.platform.sendinput.is_elevated", lambda pid: pid in fake.elevated)
    monkeypatch.setattr("jarvis.tools.ui.tools.run_com", _run_inline)
    monkeypatch.setattr("jarvis.tools.ui.tools.READBACK_DELAY_S", 0)
    monkeypatch.setattr("jarvis.tools.messaging.whatsapp.run_com", _run_inline)
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


class FakeTab:
    """One browser tab: a page made of a title, text, and elements. Records what tools did."""

    def __init__(self) -> None:
        self.url = "about:blank"
        self.title = ""
        self.text = ""
        self.elements: list[PageElement] = []
        self.visits: list[str] = []
        self.clicks: list[int] = []
        self.fills: list[tuple[int, str, bool]] = []
        self.redirect: str | None = None  # where the next goto really ends up

    def show(self, url: str, title: str, text: str = "", *elements: PageElement) -> None:
        self.url, self.title, self.text, self.elements = url, title, text, list(elements)

    async def goto(self, url: str, timeout_s: float) -> None:
        self.visits.append(url)
        self.url = self.redirect or url
        self.redirect = None

    async def snapshot(self, chars: int, elements: int, everything: bool = False) -> PageSnapshot:
        shown = self.elements if everything else self.elements[:elements]
        return PageSnapshot(self.title, self.url, self.text[:chars], len(self.text) > chars, shown)

    async def click(self, element_id: int) -> None:
        self.clicks.append(element_id)

    async def fill(self, element_id: int, text: str, submit: bool) -> None:
        self.fills.append((element_id, text, submit))

    async def blank(self) -> None:
        self.url = "about:blank"


class FakeBrowser:
    def __init__(self) -> None:
        self.tab = FakeTab()
        self.profiles: list[str] = []

    async def page(self, profile: str = "browser") -> FakeTab:
        self.profiles.append(profile)
        return self.tab

    async def aclose(self) -> None:
        return None


class FakeWhatsApp:
    """Records messages instead of sending them."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []
        self.result = Sent("web", SendStatus.DELIVERED)
        self.error: Exception | None = None

    async def send(self, phone: str, message: str) -> Sent:
        if self.error is not None:
            raise self.error
        self.sent.append((phone, message))
        return self.result


class FakeNotificationCenter:
    """The Windows notification center: tests add toasts; `denied` mimics access turned off."""

    NOW = datetime(2026, 10, 15, 12, 0, tzinfo=UTC)

    def __init__(self) -> None:
        self.toasts: list[RawNotification] = []
        self.denied = False
        self.reads = 0

    def add(
        self, app: str, title: str, body: str, *, minutes_ago: float = 1, app_id: str = ""
    ) -> RawNotification:
        toast = RawNotification(
            win_id=len(self.toasts) + 1,
            app_id=app_id or f"{app}.App",
            app=app,
            title=title,
            body=body,
            created=self.NOW - timedelta(minutes=minutes_ago),
        )
        self.toasts.append(toast)
        return toast

    async def read(self) -> list[RawNotification]:
        self.reads += 1
        if self.denied:
            raise NotificationAccessError("Windows does not let Jarvis read notifications.")
        return list(self.toasts)


@pytest.fixture
def notification_center() -> FakeNotificationCenter:
    return FakeNotificationCenter()


@pytest.fixture
def fake_browser() -> FakeBrowser:
    return FakeBrowser()


@pytest.fixture
def fake_whatsapp() -> FakeWhatsApp:
    return FakeWhatsApp()


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
def make_app(
    settings: Settings,
    web: FakeWeb,
    yahoo: FakeYahoo,
    fake_browser: FakeBrowser,
    fake_whatsapp: FakeWhatsApp,
    notification_center: FakeNotificationCenter,
) -> MakeApp:
    def factory(
        script: Sequence[LLMReply | BaseException | Hang] = (),
        *,
        channel: FakeChannel | None = None,
        search: FakeSearch | None = None,
        registry: Registry | None = None,
        overrides: dict[str, Any] | None = None,
        env: dict[str, str] | None = None,
        cloud: dict[str, Any] | None = None,
    ) -> Harness:
        cfg = settings
        if overrides:
            cfg = load_settings(
                REPO / "config",
                include_local=False,
                env_file=settings.data_dir / "missing.env",
                overrides={"data_dir": str(settings.data_dir), **overrides},
            )
        # Only fake cloud models, ever: a real API key in the environment must not matter.
        cfg = cfg.model_copy(deep=True)
        cfg.router.cloud = list(cloud or {})
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
            browser=fake_browser,  # type: ignore[arg-type]
            contacts=ContactBook(db, cfg.contacts),
            whatsapp=fake_whatsapp,  # type: ignore[arg-type]
            notifications=Notifications(
                db,
                cfg.notifications,
                reader=notification_center.read,
                clock=lambda: FakeNotificationCenter.NOW,
            ),
            memory=MemoryStore(db),
        )
        router = Router(cfg, db, clients=cloud or {}, clock=lambda: FakeNotificationCenter.NOW)
        app = build_app(
            cfg, chan, llm=llm, services=services, registry=registry, db=db, router=router
        )
        harness = Harness(app, llm, chan, tts)
        harness.files_root = files_root
        return harness

    return factory
