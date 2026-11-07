"""Phase 28: the screen through a local vision model, and the daily AI and tech digest."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from jarvis.llm.types import LLMReply, ToolCall
from jarvis.platform.ocr import Line
from jarvis.tools import news, vision
from jarvis.tools.base import ToolContext
from tests.conftest import FakeWeb, Harness, MakeApp

NOW = datetime.now(UTC)


def context(h: Harness) -> ToolContext:
    return ToolContext(h.app.settings, h.channel, h.app.services, "s", "t")


async def call(h: Harness, tool: str, **args: Any) -> Any:
    return await h.app.agent.executor.run(ToolCall("c1", tool, json.dumps(args)), context(h))


# The screen


@pytest.fixture
def screen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A 64 by 32 screen with OCR text, and Ollama answering; records what was sent."""
    seen: dict[str, Any] = {"reloads": []}
    width, height = 64, 32
    monkeypatch.setattr(
        vision.ocr, "grab", lambda rect: (b"\x80" * width * height * 4, width, height, 0, 0)
    )

    async def recognize(*args: Any) -> list[Line]:
        return [Line("Budget 2026.xlsx - Excel", ()), Line("password: hunter2", ())]

    monkeypatch.setattr(vision.ocr, "recognize", recognize)

    async def ask(root: str, model: str, prompt: str, png: bytes, keep: float, limit: float) -> str:
        seen.update(root=root, model=model, prompt=prompt, png=png, keep=keep)
        return seen.get("answer", "Excel shows Budget 2026.xlsx with a read-only warning.")

    async def reload(root: str, model: str) -> None:
        seen["reloads"].append(model)

    monkeypatch.setattr(vision, "ask_vision", ask)
    monkeypatch.setattr(vision, "reload_main_model", reload)
    return seen


async def test_the_screen_goes_to_the_local_vision_model_with_ocr_text(
    make_app: MakeApp, screen: dict[str, Any]
) -> None:
    h = make_app()
    outcome = await call(h, "look_at_screen", question="is anything wrong?")
    assert outcome.result.speech == "Excel shows Budget 2026.xlsx with a read-only warning."
    assert screen["root"] == "http://localhost:11434"  # Ollama itself, never a cloud model
    assert screen["model"] == "gemma3:4b"
    assert screen["png"].startswith(b"\x89PNG")
    assert "Budget 2026.xlsx - Excel" in screen["prompt"]
    assert "is anything wrong?" in screen["prompt"]
    assert "hunter2" not in screen["prompt"]  # secrets are hidden before the model sees them
    assert outcome.tool.untrusted


async def test_the_main_model_is_loaded_again_after(
    make_app: MakeApp, screen: dict[str, Any]
) -> None:
    import asyncio

    h = make_app()
    await call(h, "look_at_screen")
    await asyncio.sleep(0)
    assert screen["reloads"] == ["jarvis-hermes3"]
    assert screen["keep"] == 30


async def test_secrets_in_the_answer_are_hidden(make_app: MakeApp, screen: dict[str, Any]) -> None:
    screen["answer"] = "A login form; the API key is sk-abcdefghijklmnopqrstuvwxyz123456."
    h = make_app()
    outcome = await call(h, "look_at_screen")
    assert "sk-abcdef" not in outcome.result.speech
    assert outcome.result.data["secrets_hidden"] >= 1


async def test_vision_can_be_turned_off(make_app: MakeApp, screen: dict[str, Any]) -> None:
    h = make_app(overrides={"vision": {"enabled": False}})
    assert not (await call(h, "look_at_screen")).result.ok


def test_screenshots_are_scaled_down() -> None:
    from io import BytesIO

    from PIL import Image

    png = vision.screen_png(b"\x00" * 4000 * 1000 * 4, 4000, 1000, 1600)
    assert Image.open(BytesIO(png)).size == (1600, 400)
    assert vision.ollama_root("http://localhost:11434/v1/") == "http://localhost:11434"


# The news


def rss(*items: tuple[str, str, datetime], title: str = "Feed") -> bytes:
    body = "".join(
        f"<item><title>{t}</title><link>{link}</link>"
        f"<pubDate>{when.strftime('%a, %d %b %Y %H:%M:%S +0000')}</pubDate>"
        f"<description>&lt;p&gt;About {t}&lt;/p&gt;</description></item>"
        for t, link, when in items
    )
    return f"<rss><channel><title>{title}</title>{body}</channel></rss>".encode()


def atom(*entries: tuple[str, str, datetime]) -> bytes:
    body = "".join(
        f'<entry><title>{t}</title><link rel="alternate" href="{link}"/>'
        f"<updated>{when.isoformat()}</updated><summary>Sum {t}</summary></entry>"
        for t, link, when in entries
    )
    return (
        f'<feed xmlns="http://www.w3.org/2005/Atom"><title>The Verge</title>{body}</feed>'.encode()
    )


def test_rss_and_atom_are_read() -> None:
    old = NOW - timedelta(days=3)
    stories = news.parse_feed(
        rss(("A", "https://a.test/1", NOW), ("B", "https://a.test/2", old)),
        "https://hnrss.org/frontpage",
    )
    assert [(s.title, s.source, s.summary) for s in stories] == [
        ("A", "Hacker News", "About A"),
        ("B", "Hacker News", "About B"),
    ]
    entries = news.parse_feed(
        atom(("C", "https://v.test/c", NOW)), "https://www.theverge.com/rss/x"
    )
    assert (entries[0].title, entries[0].link, entries[0].source) == (
        "C",
        "https://v.test/c",
        "The Verge",
    )


def test_a_broken_feed_is_an_error_not_a_crash() -> None:
    with pytest.raises(news.ProviderError):
        news.parse_feed(b"<html>not a feed", "https://x.test/")


def test_stories_take_turns_drop_old_ones_and_repeats() -> None:
    def story(title: str, hours: float, source: str) -> news.Story:
        return news.Story(title, f"https://{source}/{title}", source, NOW - timedelta(hours=hours))

    one = [
        story("OpenAI ships a new model", 1, "a"),
        story("Old news", 50, "a"),
        story("Chips", 2, "a"),
    ]
    two = [story("OpenAI ships new model - Reuters", 3, "Reuters"), story("Robots", 1, "b")]
    chosen = news.choose([one, two], NOW, 36, 5)
    assert [s.title for s in chosen] == ["OpenAI ships a new model", "Robots", "Chips"]


class FakeCloud:
    def __init__(self, text: str, fail: bool = False) -> None:
        self.text, self.fail = text, fail
        self.name, self.sent = "groq", []

    @property
    def model(self) -> str:
        return "cloud-model"

    async def complete(
        self, messages: list[dict[str, Any]], tools: list[Any], *, private: bool
    ) -> LLMReply:
        from jarvis.llm.types import LLMError

        assert private is False
        self.sent.append(messages)
        if self.fail:
            raise LLMError("down")
        return LLMReply(text=self.text, model="cloud-model", latency_ms=1)


class FakeRouter:
    def __init__(self, *clouds: FakeCloud) -> None:
        self.clouds = list(clouds)
        self.failures: list[str] = []

    def available(self) -> list[FakeCloud]:
        return self.clouds

    def failed(self, model: Any, reason: str) -> None:
        self.failures.append(reason)

    def succeeded(self, model: Any, reply: Any) -> None:
        return None


@pytest.fixture
def feeds(make_app: MakeApp, web: FakeWeb, tmp_path: Path) -> Harness:
    web.route("hnrss.org/frontpage", content=rss(("Libghostty 1.0", "https://hn.test/1", NOW)))
    web.route(
        "www.theverge.com/rss",
        content=atom(
            ("OpenAI valued at $1.25 trillion", "https://verge.test/2", NOW - timedelta(hours=2))
        ),
    )
    feeds = [
        "https://hnrss.org/frontpage?points=150",
        "https://www.theverge.com/rss/ai/index.xml",
        "https://down.test/feed",
    ]
    h = make_app(overrides={"news": {"feeds": feeds, "folder": str(tmp_path / "Jarvis News")}})
    return h


async def test_the_digest_is_written_by_the_cloud_and_saved_with_links(
    feeds: Harness, tmp_path: Path
) -> None:
    cloud = FakeCloud(
        "1. Libghostty, a terminal library, reached version 1.0.\n"
        "2. OpenAI is now valued at 1.25 trillion dollars."
    )
    feeds.app.services.cloud = FakeRouter(cloud)  # type: ignore[assignment]
    outcome = await call(feeds, "ai_news")
    assert outcome.result.speech.startswith("2 AI and tech stories today. Libghostty")
    assert outcome.result.data["feeds_failed"] == ["https://down.test/feed"]
    saved = next((tmp_path / "Jarvis News").glob("*.md")).read_text("utf-8")
    assert (
        "- **Libghostty 1.0** (Hacker News): Libghostty, a terminal library, reached version 1.0. [link](https://hn.test/1)"
        in saved
    )
    assert "written by cloud-model" in saved
    assert (
        "untrusted" in cloud.sent[0][1]["content"].casefold()
        or "data" in cloud.sent[0][1]["content"]
    )


async def test_the_local_model_writes_it_when_the_cloud_is_down(feeds: Harness) -> None:
    feeds.app.services.cloud = FakeRouter(FakeCloud("", fail=True))  # type: ignore[assignment]
    feeds.llm._script = [
        LLMReply(text="1. Local line one.\n2. Local line two.", model="fake-model", latency_ms=1)
    ]
    outcome = await call(feeds, "ai_news")
    assert outcome.result.data["model"] == "fake-model"
    assert "Local line one." in outcome.result.speech


async def test_a_story_the_model_skips_keeps_its_title(feeds: Harness) -> None:
    feeds.app.services.cloud = FakeRouter(FakeCloud("1. Only the first one."))  # type: ignore[assignment]
    outcome = await call(feeds, "ai_news")
    lines = [s["line"] for s in outcome.result.data["stories"]]
    assert lines == ["Only the first one.", "OpenAI valued at $1.25 trillion."]


async def test_the_saved_digest_is_read_again_until_refreshed(feeds: Harness, web: FakeWeb) -> None:
    feeds.app.services.cloud = FakeRouter(FakeCloud("1. One.\n2. Two."))  # type: ignore[assignment]
    await call(feeds, "ai_news")
    before = len(web.requests)
    again = await call(feeds, "ai_news")
    assert len(web.requests) == before  # read from the file
    assert again.result.data["stories"][0]["line"] == "One."


async def test_no_feeds_reachable(make_app: MakeApp, tmp_path: Path) -> None:
    h = make_app(overrides={"news": {"feeds": ["https://down.test/a"], "folder": str(tmp_path)}})
    outcome = await call(h, "ai_news")
    assert "couldn't reach the news feeds" in outcome.result.error


async def test_the_briefing_counts_the_stories(feeds: Harness) -> None:
    line = await news.briefing_line(context(feeds))
    assert line == '2 AI and tech stories today; say "what\'s new in AI" to hear them.'


# Found by the live run with the real feeds


def test_the_same_story_from_two_feeds_is_kept_once() -> None:
    def story(title: str, source: str) -> news.Story:
        return news.Story(title, f"https://{source}.test/", source, NOW)

    verge = story("OpenAI valued at $1.25 trillion, as rival Anthropic nears its IPO", "verge")
    tc = story(
        "OpenAI reportedly raises an additional $11 billion at a $1.25 trillion valuation", "tc"
    )
    other = story("OpenAI opens an office in Bengaluru", "x")
    assert news.same_story(verge, tc)
    assert not news.same_story(verge, other)  # only "openai" in common
    assert [s.title for s in news.choose([[verge], [tc], [other]], NOW, 36, 5)] == [
        verge.title,
        other.title,
    ]


def test_link_only_descriptions_are_not_given_to_the_model() -> None:
    hn = "Article URL: https://x.test Comments URL: https://hn.test/item?id=1 Points: 200"
    assert news.useful_text(hn) == ""
    assert news.useful_text("Comments") == ""
    assert news.useful_text("A real summary.") == "A real summary."


async def test_refresh_reads_a_digest_made_within_the_hour(feeds: Harness, web: FakeWeb) -> None:
    # The benchmark: the model asked for refresh=true every time.
    import os
    import time

    feeds.app.services.cloud = FakeRouter(FakeCloud("1. One.\n2. Two."))  # type: ignore[assignment]
    first = await call(feeds, "ai_news")
    before = len(web.requests)
    await call(feeds, "ai_news", refresh=True)
    assert len(web.requests) == before
    old = time.time() - 2 * 3600
    os.utime(first.result.data["file"], (old, old))
    await call(feeds, "ai_news", refresh=True)
    assert len(web.requests) > before  # an older digest is made again
