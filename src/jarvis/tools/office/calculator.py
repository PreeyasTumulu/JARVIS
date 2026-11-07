"""Show a sum in the Windows Calculator app: "work out 18 percent of 2400 in the calculator".

Jarvis works the sum out itself first (`calculate`), then opens Calculator, switches it to
Scientific (so 2 + 3 * 4 is 14, not 20), clears it, types the sum, presses Enter, and reads
the display back through UI Automation. The answer said is Jarvis's own; when Calculator
shows something else, Jarvis says so instead of trusting either quietly. Only + - * / and
brackets are typed; powers and square roots are answered without the app.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

from jarvis.platform import sendinput, uia
from jarvis.platform.com import run_com
from jarvis.tools.apps.tools import resolve_app
from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.tools.system.arithmetic import evaluate, spoken_number
from jarvis.tools.ui.tools import bring_forward, live_window, still_in_front

VK_ESCAPE, VK_RETURN, VK_MENU, VK_2 = 0x1B, 0x0D, 0x12, 0x32
_TYPABLE = re.compile(r"^[\d.+\-*/() ]+$")
_DISPLAY = re.compile(r"^Display is\s+(.+)$", re.I)
SETTLE_S = 0.4  # Calculator redraws after each step
MINUS = chr(0x2212)  # Calculator writes negative numbers with the minus sign


def typable(expression: str) -> str:
    """The sum as Calculator's keyboard takes it, or a ToolError for what it cannot take."""
    plain = expression.replace(" ", "")
    if "**" in plain or "sqrt" in plain or "%" in plain or not _TYPABLE.match(plain):
        raise ToolError(
            "Calculator is typed only plain + - * / sums; use calculate for powers, "
            "roots, and percentages written with %."
        )
    return plain


def display_value(texts: list[str]) -> float | None:
    """The number on Calculator's display ("Display is 1,234.5"), from its accessible text."""
    for text in texts:
        found = _DISPLAY.match(text.strip())
        if found:
            raw = found[1].replace(",", "").replace(MINUS, "-").strip()
            try:
                return float(raw)
            except ValueError:
                return None
    return None


async def _read_display(hwnd: int, max_chars: int) -> float | None:
    content, _ = await run_com(uia.read_window, hwnd, max_chars)
    return display_value([*content.lines, *(c.name for c in content.controls)])


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=30)
async def calculator_show(ctx: ToolContext, expression: str) -> ToolResult:
    """Show a sum in the Windows Calculator app and read its answer, only when the user asks
    for the Calculator app ("in the calculator"). For an answer alone, use calculate.

    Args:
        expression: The sum with + - * / and brackets, for example "18/100*2400".
    """
    keys = typable(expression)
    mine = evaluate(keys)
    window = await live_window(ctx, "Calculator", start=True)
    await bring_forward(window, "Calculator")
    await asyncio.to_thread(sendinput.press_combo, [VK_MENU], VK_2)  # Scientific
    await asyncio.sleep(SETTLE_S)
    await asyncio.to_thread(sendinput.press_combo, [], VK_ESCAPE)  # clear
    await still_in_front(window, "Calculator", " before I typed the sum")
    await asyncio.to_thread(sendinput.type_unicode, keys)
    await asyncio.to_thread(sendinput.press_combo, [], VK_RETURN)
    await asyncio.sleep(SETTLE_S)
    shown = await _read_display(window.hwnd, ctx.settings.ui.read_max_chars)
    answer = spoken_number(mine)
    data: dict[str, Any] = {"expression": keys, "value": answer, "calculator": shown}
    if shown is None:
        return ToolResult.success(
            data, speech=f"It's {answer}. I typed it into Calculator but couldn't read its display."
        )
    if abs(shown - mine) > max(1e-9, abs(mine) * 1e-9):
        return ToolResult.success(
            data,
            speech=f"Calculator shows {spoken_number(shown)}, but I get {answer}. "
            "Check what was typed.",
        )
    return ToolResult.success(data, speech=f"It's {answer}, and Calculator shows the same.")


@calculator_show.preparer
async def _prepare_calculator(ctx: ToolContext, args: dict[str, Any]) -> Prepared:
    keys = typable(args["expression"])
    evaluate(keys)  # refuse a sum that has no answer before opening anything
    await resolve_app(ctx, "Calculator")
    return Prepared(args={"expression": keys}, summary=f"Show {keys} in Calculator")
