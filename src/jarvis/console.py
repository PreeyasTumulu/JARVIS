"""Terminal channel: renders agent events and answers confirmations and questions by keyboard."""

from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import Sequence
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.panel import Panel

from jarvis.core.channel import ConfirmationRequest
from jarvis.core.events import (
    AssistantMessage,
    Event,
    ModelReplied,
    ToolCallFinished,
    ToolCallStarted,
    TurnFinished,
)

_YES = {"y", "yes"}


async def read_line() -> str:
    """Read a line without blocking the event loop, so Ctrl+C and timeouts still work."""
    if sys.platform != "win32" or not sys.stdin.isatty():
        line: str = await asyncio.to_thread(sys.stdin.readline)
        return line.rstrip("\r\n")

    import msvcrt

    chars: list[str] = []
    while True:
        while msvcrt.kbhit():
            char = msvcrt.getwch()
            if char in ("\r", "\n"):
                sys.stdout.write("\n")
                sys.stdout.flush()
                return "".join(chars)
            if char in ("\x00", "\xe0"):  # arrow and function keys come as two characters
                msvcrt.getwch()
            elif char == "\x08":
                if chars:
                    chars.pop()
                    sys.stdout.write("\b \b")
            else:
                chars.append(char)
                sys.stdout.write(char)
            sys.stdout.flush()
        await asyncio.sleep(0.03)


class ConsoleChannel:
    name = "cli"

    def __init__(self, console: Console) -> None:
        self._console = console

    async def confirm(self, request: ConfirmationRequest) -> bool:
        body = f"[bold]{escape(request.summary)}[/bold]"
        if request.reason:
            body += f"\n[dim]{escape(request.reason)}[/dim]"
        self._console.print(Panel(body, title="Confirm", border_style="yellow", expand=False))
        self._console.print(
            f"[yellow]Allow? y/N ({request.timeout_s:.0f}s to answer)[/yellow] ", end=""
        )
        answer = await read_line()
        return answer.strip().casefold() in _YES

    async def ask(self, question: str, options: Sequence[str] | None = None) -> str:
        self._console.print(f"[bold magenta]jarvis asks[/bold magenta] {escape(question)}")
        for number, option in enumerate(options or [], start=1):
            self._console.print(f"  {number}. {escape(option)}")
        self._console.print("[magenta]>[/magenta] ", end="")
        answer = (await read_line()).strip()
        if options and answer.isdigit() and 1 <= int(answer) <= len(options):
            return options[int(answer) - 1]
        return answer


class ConsoleRenderer:
    """Prints the live tool log and replies."""

    def __init__(self, console: Console, *, verbose: bool = False) -> None:
        self._console = console
        self._verbose = verbose

    def __call__(self, event: Event) -> None:
        console = self._console
        match event:
            case ModelReplied(model=model, latency_ms=ms, tool_calls=calls):
                detail = f", {calls} tool call(s)" if calls else ""
                console.print(f"  [dim]{escape(model)} {ms / 1000:.1f}s{detail}[/dim]")
            case ToolCallStarted(tool=tool, args=args, risk=risk):
                console.print(
                    f"  [cyan]>[/cyan] [bold]{escape(tool)}[/bold]({escape(_short_args(args))})"
                    f" [dim]{risk}[/dim]"
                )
            case ToolCallFinished(ok=ok, summary=summary, decision=decision, duration_ms=ms):
                mark = "[green]ok[/green]" if ok else "[red]x[/red]"
                console.print(f"    {mark} {escape(summary)} [dim]{decision}, {ms} ms[/dim]")
            case AssistantMessage(text=text):
                console.print(f"[bold green]jarvis[/bold green] > {escape(text)}")
            case TurnFinished(status=status, latency_ms=ms) if self._verbose:
                console.print(f"  [dim]turn {status} in {ms / 1000:.1f}s[/dim]")
            case _:
                pass


def _short_args(args: dict[str, Any], limit: int = 80) -> str:
    text = ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in args.items())
    return text if len(text) <= limit else text[: limit - 3] + "..."
