"""Tools for talking to the user: speak out loud and ask clarifying questions."""

from __future__ import annotations

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolResult
from jarvis.tools.registry import tool


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=60)
async def speak(ctx: ToolContext, text: str) -> ToolResult:
    """Say something out loud through the laptop speakers.

    Use this only when the user asks you to say, read, or announce something aloud.

    Args:
        text: The exact words to say.
    """
    await ctx.services.tts.speak(text)
    return ToolResult.success(data={"spoken": text})


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PRIVATE, timeout_s=120)
async def ask_user(ctx: ToolContext, question: str, options: list[str] | None = None) -> ToolResult:
    """Ask the user a short question when the request is ambiguous or a detail is missing.

    Args:
        question: One short, direct question.
        options: Optional list of choices for the user to pick from.
    """
    answer = await ctx.channel.ask(question, options)
    return ToolResult.success(data={"answer": answer})
