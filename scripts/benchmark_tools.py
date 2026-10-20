"""Benchmark local models on tool choice accuracy and latency, using Jarvis's real prompt and tools.

Each command is sent once, on its own, and the first tool call is checked against what a
correct assistant would do. Nothing is executed. Results are written as a Markdown report.

Usage:
    uv run python scripts/benchmark_tools.py
    uv run python scripts/benchmark_tools.py --models jarvis-hermes3 jarvis-hermes3-3b
    uv run python scripts/benchmark_tools.py --mcp   # also the MCP servers' tools (their
                                                     # secrets must be set; only listed)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import subprocess
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from jarvis.config import load_settings
from jarvis.core.prompts import system_prompt
from jarvis.core.semantic_routing import SemanticRouter
from jarvis.core.tool_routing import needs_meaning, select_tools
from jarvis.llm.client import LLMClient
from jarvis.llm.types import LLMError
from jarvis.tools.catalog import build_registry
from jarvis.tools.mcp.hub import McpHub
from jarvis.tools.mcp.tools import register_all

ROOT = Path(__file__).resolve().parents[1]
NO_TOOL = "(no tool)"


@dataclass(frozen=True)
class Case:
    text: str
    expected: frozenset[str]
    arg: tuple[str, str] | None = None  # (argument, substring it must contain)


def case(text: str, *expected: str, arg: tuple[str, str] | None = None) -> Case:
    return Case(text, frozenset(expected), arg)


CASES = [
    case("open notepad", "open_app", arg=("name", "notepad")),
    case("can you launch vs code", "open_app", arg=("name", "code")),
    case("start docker", "open_app", arg=("name", "docker")),
    case("open whatsapp please", "open_app", arg=("name", "whatsapp")),
    case("bring up the calculator", "open_app", arg=("name", "calc")),
    case("open chrome", "open_app", arg=("name", "chrome")),
    case("search the web for the latest python release", "web_search"),
    case("who won the most recent cricket world cup", "web_search"),
    case("find reviews of the RTX 3050 laptop GPU", "web_search"),
    case("what is the latest news about OpenAI", "web_search"),
    case("look up how tall the Burj Khalifa is", "web_search"),
    case("say hello", "speak"),
    case("read this out loud: the build passed", "speak", arg=("text", "build passed")),
    case("announce that the meeting starts in five minutes", "speak", arg=("text", "meeting")),
    case("open the app", "ask_user", NO_TOOL),
    case("search for it", "ask_user", NO_TOOL),
    case("hi jarvis", NO_TOOL),
    case("what is 15 times 12", NO_TOOL),
    case("thanks, that's all", NO_TOOL),
    case("tell me a one line joke", NO_TOOL, "speak"),
    # Phase 3
    case("switch to vs code", "focus_app", arg=("name", "code")),
    case("close the calculator", "close_app", arg=("name", "calc")),
    case("what docker containers are running", "docker_list"),
    case("stop the postgres container", "docker_stop", arg=("container", "postgres")),
    case("show me the logs of the backend container", "docker_logs", arg=("container", "backend")),
    case("find my resume", "find_file", arg=("query", "resume")),
    case("open the jarvis readme", "find_file", "open_file"),
    case("what is this file", "get_selected_file"),
    case("open github.com", "open_url", arg=("url", "github")),
    case("open the jarvis project folder in vs code", "find_file", "vscode_open"),
    # Phase 4
    case("what's reliance trading at", "market_data", arg=("query", "reliance")),
    case("price of apple stock", "market_data", arg=("query", "apple")),
    case("how is the nifty doing today", "market_data", arg=("query", "nifty")),
    case("bitcoin price in rupees", "crypto_price", arg=("coin", "bitcoin")),
    case("convert 100 dollars to rupees", "convert_currency"),
    case("what's the weather tomorrow", "weather", arg=("day", "tomorrow")),
    case("is it going to rain in mumbai today", "weather", arg=("place", "mumbai")),
    case("summarize https://www.python.org/about/", "fetch_page", arg=("url", "python.org")),
    case("set the volume to 30", "set_volume"),
    case("make the screen dimmer", "set_brightness"),
    case("lock my laptop", "lock_screen"),
    case("take a screenshot", "screenshot"),
    case("what did I copy", "clipboard_read"),
    case("set a timer for 5 minutes", "set_timer"),
    case("remind me in 10 minutes to stretch", "set_reminder", arg=("message", "stretch")),
    # Phase 6
    case("type hello world in notepad", "type_text", arg=("text", "hello world")),
    case("click the File menu in notepad", "click", arg=("target", "file")),
    case("press ctrl s in notepad", "press_keys", arg=("keys", "s")),
    case("what does the notepad window say", "read_window_text", arg=("app", "notepad")),
    case("message mom that I'll be late", "send_whatsapp", arg=("contact", "mom")),
    case("tell Ravi on whatsapp that the meeting moved to 5", "send_whatsapp"),
    case("send a whatsapp to dad saying I reached home", "send_whatsapp", arg=("contact", "dad")),
    case("search amazon for wireless earbuds in your browser", "browser_open", "browser_type"),
    case("open github.com in your browser so you can sign me in", "browser_open"),
    case("on the page in your browser, click today's deals", "browser_click", "browser_read"),
    case("what does the page in your browser say", "browser_read"),
    # Phase 7
    case("read my notifications", "read_notifications"),
    case("anything new from Ravi", "read_notifications", arg=("person", "ravi")),
    case("did mom message me", "read_notifications", arg=("person", "mom")),
    # Phase 8
    case("remember that my manager is Ravi", "remember", arg=("fact", "ravi")),
    case("what do you remember about me", "list_memories"),
    case("forget that my manager is Ravi", "forget", arg=("what", "manager")),
    case("search youtube for lofi music", "search_site", arg=("site", "youtube")),
    case("open wikipedia and search for alan turing", "search_site", arg=("site", "wiki")),
    case("find running shoes on amazon", "search_site", arg=("site", "amazon")),
    case("call mom", "call_contact", arg=("contact", "mom")),
    case("phone ravi please", "call_contact", arg=("contact", "ravi")),
    # Phase 10 (exact phrases such as "pause the music" never reach the model)
    case("could you skip to the next track", "media_control", arg=("action", "next")),
    case("resume the song I was listening to", "media_control", arg=("action", "play")),
    case("pause the video in brave", "media_control", arg=("action", "pause")),
    case("which song is playing right now", "now_playing"),
    # Phase 11
    case("any new email", "read_mail"),
    case("check my emails from ravi", "read_mail", arg=("sender", "ravi")),
    case("read the email about the project update", "read_email", "read_mail"),
    case(
        "reply to ravi's email that I'll send the report tonight",
        "reply_email",
        "read_mail",
        "read_email",
    ),
    case("what's on my calendar today", "calendar_events", arg=("day", "today")),
    case("what's my next meeting", "calendar_events", arg=("day", "next")),
    case("am I free on friday", "calendar_events", arg=("day", "friday")),
    # Phase 15
    case("what's on my screen", "read_screen"),
    case("read my screen to me", "read_screen"),
    # Phase 14 ("good morning" and "brief me" never reach the model)
    case("what did I ask about docker last week", "recall", arg=("about", "docker")),
    case("when did I last ask you about the weather", "recall"),
    case("give me a rundown of my day", "briefing"),
    # Phase 13: paraphrases with none of the keywords (semantic routing's job)
    case("what have I got lined up tomorrow", "calendar_events"),
    case("anything booked for friday evening", "calendar_events"),
    case("is it going to pour in mumbai later", "weather", arg=("place", "mumbai")),
    case("it's too loud, bring it down", "set_volume"),
    case("has anybody tried to reach me", "read_notifications", "read_mail"),
    case("drop my sister a line saying I'm home", "send_whatsapp"),
]

# Phase 12: GitHub through its MCP server (run with --mcp). For "my repo" a first call to
# github_get_me (to learn the user's account) is also right.
MCP_CASES = [
    case("any open issues on my JARVIS repo on github", "github_list_issues",
         "github_search_issues", "github_get_me"),
    case("show the pull requests on PreeyasTumulu/JARVIS", "github_list_pull_requests",
         arg=("repo", "jarvis")),
    case("who am I on github", "github_get_me"),
    case("open a github issue on PreeyasTumulu/JARVIS titled wake word misses quiet voices",
         "github_issue_write", arg=("title", "wake word")),
    case("what were the last commits on PreeyasTumulu/JARVIS", "github_list_commits"),
    case("find github repos about wake word detection", "github_search_repositories"),
    case("read issue 12 on PreeyasTumulu/JARVIS", "github_issue_read"),
    case("comment on issue 12 in PreeyasTumulu/JARVIS that it is fixed",
         "github_add_issue_comment", arg=("body", "fixed")),
]  # fmt: skip


@dataclass
class Row:
    case: Case
    chosen: str
    args: str
    latency_ms: int
    correct: bool
    from_text: bool = False
    error: str = ""


@dataclass
class Report:
    model: str
    load_ms: int
    placement: str
    rows: list[Row] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return sum(r.correct for r in self.rows) / len(self.rows) if self.rows else 0.0

    def latency(self, quantile: float) -> int:
        values = sorted(r.latency_ms for r in self.rows if not r.error)
        if not values:
            return 0
        return values[min(len(values) - 1, int(quantile * len(values)))]


def ollama_placement(model: str) -> str:
    """The PROCESSOR column of `ollama ps`, for example '35%/65% CPU/GPU'."""
    try:
        output = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    for line in output.splitlines()[1:]:
        if line.split() and line.split()[0].startswith(model):
            for marker in ("CPU/GPU", "GPU", "CPU"):
                if marker in line:
                    before = line.split(marker)[0].split()
                    return f"{before[-1]} {marker}" if before else marker
    return "unknown"


def unload_all_models() -> None:
    """Free GPU memory so each model is measured alone, not squeezed by the previous one."""
    try:
        output = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=10).stdout
        for line in output.splitlines()[1:]:
            if line.split():
                subprocess.run(["ollama", "stop", line.split()[0]], capture_output=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        pass


async def run_model(model: str, routing: str, mcp: bool = False, semantic: bool = True) -> Report:
    unload_all_models()
    settings = load_settings()
    provider = settings.llm.active().model_copy(update={"model": model})
    client = LLMClient(provider)
    registry = build_registry()
    cases = list(CASES)
    meaning = (
        SemanticRouter(
            settings.agent, settings.llm.providers["local"].base_url, settings.data_dir / "cache"
        )
        if semantic
        else None
    )
    hub = McpHub(settings.mcp, log_dir=settings.data_dir / "logs")
    if mcp:
        added = register_all(registry, hub, await hub.start(), hub.configured())
        cases += [c for c in MCP_CASES if c.expected & set(added)]
        print(f"  MCP tools: {len(added)}")
    tools = registry.schemas()
    system = {"role": "system", "content": system_prompt()}

    started = time.perf_counter()
    await client.complete([system, {"role": "user", "content": "hello"}], tools)  # loads model
    report = Report(model, int((time.perf_counter() - started) * 1000), ollama_placement(model))

    for item in cases:
        messages = [system, {"role": "user", "content": item.text}]
        meant = (
            await meaning.groups(item.text)
            if meaning is not None and needs_meaning(item.text, registry)
            else []
        )
        offered = (
            [tool.schema() for tool in select_tools(item.text, registry, meant)]
            if routing == "keywords"
            else tools
        )
        try:
            reply = await client.complete(messages, offered)
        except LLMError as exc:
            report.rows.append(Row(item, "error", "", 0, False, error=str(exc)))
            continue
        call = reply.tool_calls[0] if reply.tool_calls else None
        chosen = call.name if call else NO_TOOL
        args = call.arguments if call else ""
        correct = chosen in item.expected
        if correct and call and item.arg:
            name, needle = item.arg
            try:
                value = str(json.loads(args).get(name, ""))
            except (json.JSONDecodeError, AttributeError):
                value = ""
            correct = needle.casefold() in value.casefold()
        report.rows.append(
            Row(item, chosen, args, reply.latency_ms, correct, reply.parsed_from_text)
        )
        mark = "ok " if correct else "BAD"
        print(f"  {mark} {reply.latency_ms:>6} ms  {item.text!r} -> {chosen} {args}")
    await client.aclose()
    await hub.aclose()
    return report


def render(reports: list[Report], routing: str) -> str:
    gpu = _gpu_name()
    offered = (
        "the tools keyword routing selects (all of them when nothing matches)"
        if routing == "keywords"
        else f"all {len(build_registry())} tools"
    )
    lines = [
        f"# Model benchmark (tool routing: {routing})",
        "",
        f"Run on {datetime.now():%Y-%m-%d %H:%M}, {gpu}. "
        f"Each of {len(reports[0].rows)} commands is "
        f"sent once with the Jarvis system prompt and {offered}. "
        "A case is correct "
        "if the first tool call (or no call) matches what a careful assistant would do, "
        "including a key argument where noted. Nothing is executed. Other models are "
        "unloaded first, so load time is a cold start and placement is the model alone.",
        "",
        "Regenerate with `uv run python scripts/benchmark_tools.py`.",
        "",
        "## Summary",
        "",
        "| Model | Accuracy | Median latency | p90 latency | Load time | Placement "
        "| Text fallback |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in reports:
        fallback = sum(row.from_text for row in r.rows)
        lines.append(
            f"| `{r.model}` | {r.accuracy:.0%} ({sum(x.correct for x in r.rows)}/{len(r.rows)}) "
            f"| {r.latency(0.5) / 1000:.1f} s | {r.latency(0.9) / 1000:.1f} s "
            f"| {r.load_ms / 1000:.1f} s | {r.placement} | {fallback} |"
        )
    for r in reports:
        lines += ["", f"## `{r.model}` details", "", "| Command | Expected | Got | Args | Time |"]
        lines.append("|---|---|---|---|---|")
        for row in r.rows:
            expected = " or ".join(sorted(row.case.expected))
            got = row.chosen if row.correct else f"**{row.chosen}**"
            args = row.args.replace("|", "\\|")[:60] or row.error[:60]
            lines.append(
                f"| {row.case.text} | {expected} | {got} | {args} | {row.latency_ms / 1000:.1f} s |"
            )
    return "\n".join(lines) + "\n"


def _gpu_name() -> str:
    try:
        name = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,memory.total", "--format=csv,noheader"],
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return "unknown GPU"
    return name or "unknown GPU"


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--models", nargs="+", default=["jarvis-hermes3", "jarvis-hermes3-3b", "llama3.2:3b"]
    )
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "benchmarks" / "latest.md")
    parser.add_argument("--routing", choices=["keywords", "all"], default="keywords")
    parser.add_argument("--mcp", action="store_true", help="add the MCP servers' tools")
    parser.add_argument(
        "--no-semantic", action="store_true", help="keywords only (no embedding routing)"
    )
    args = parser.parse_args()

    reports = []
    for model in args.models:
        print(f"== {model}")
        reports.append(await run_model(model, args.routing, args.mcp, not args.no_semantic))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(reports, args.routing), encoding="utf-8")
    print(f"\nWrote {args.out}")
    for r in reports:
        print(f"{r.model}: {r.accuracy:.0%} correct, median {r.latency(0.5)} ms, {r.placement}")


if __name__ == "__main__":
    asyncio.run(main())
