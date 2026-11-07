"""One client for every model: any OpenAI-compatible endpoint (Ollama locally, Groq and
OpenRouter in the cloud)."""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable
from typing import Any, cast

import openai
from openai import AsyncOpenAI

from jarvis.config import ProviderSettings
from jarvis.llm.toolcall_parser import parse_text_tool_calls
from jarvis.llm.types import LLMError, LLMReply, ToolCall


class LLMClient:
    def __init__(self, provider: ProviderSettings, client: AsyncOpenAI | None = None) -> None:
        self._provider = provider
        self._client = client or AsyncOpenAI(
            base_url=provider.base_url,
            api_key=provider.api_key(),
            timeout=provider.timeout_s,
            max_retries=0,
        )

    @property
    def model(self) -> str:
        return self._provider.model

    def _kwargs(
        self, messages: list[dict[str, Any]], tools: list[dict[str, Any]] | None
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": self._provider.model,
            "messages": messages,
            "temperature": self._provider.temperature,
        }
        if self._provider.max_tokens:
            kwargs["max_tokens"] = self._provider.max_tokens
        if tools:
            kwargs["tools"] = tools
        return kwargs

    def _error(self, exc: openai.APIError) -> LLMError:
        if isinstance(exc, openai.APIConnectionError):
            return LLMError(
                f"I can't reach the model server at {self._provider.base_url}. Is Ollama running?"
            )
        if isinstance(exc, openai.NotFoundError):
            return LLMError(
                f"The model '{self._provider.model}' was not found. "
                "See docs/SETUP.md for the ollama create command."
            )
        if isinstance(exc, openai.APIStatusError):
            return LLMError(f"The model server returned an error ({exc.status_code}).")
        return LLMError(f"The model server failed ({type(exc).__name__}).")

    async def stream(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        *,
        on_text: Callable[[str], None],
    ) -> LLMReply:
        """Like `complete`, but hands reply text to `on_text` as it is written.

        Text that could be a tool call is held back, so a call is never read aloud: a reply
        that starts with "{", "<", or a code fence is held until the end, and so is everything
        from a "<" on (Hermes writes `<tool_call>` in the text when Ollama does not parse it).
        Held text that turns out not to be a call is handed over when the reply is complete.
        """
        started = time.perf_counter()
        kwargs = self._kwargs(messages, tools)
        kwargs["stream"] = True
        kwargs["stream_options"] = {"include_usage": True}
        held = _HoldBack(on_text)
        parts: dict[int, dict[str, str]] = {}
        model = self._provider.model
        usage: Any = None
        try:
            chunks = await self._client.chat.completions.create(**kwargs)
            async for chunk in chunks:
                model = getattr(chunk, "model", None) or model
                usage = getattr(chunk, "usage", None) or usage
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                for raw in getattr(delta, "tool_calls", None) or []:
                    held.stop()  # a structured call: nothing more is for speaking
                    part = parts.setdefault(raw.index, {"id": "", "name": "", "arguments": ""})
                    part["id"] = raw.id or part["id"]
                    function = getattr(raw, "function", None)
                    if function is not None:
                        part["name"] += function.name or ""
                        part["arguments"] += function.arguments or ""
                if delta.content:
                    held.add(delta.content)
        except openai.APIError as exc:
            raise self._error(exc) from exc

        calls = [
            ToolCall(
                id=part["id"] or f"call_{uuid.uuid4().hex[:12]}",
                name=part["name"],
                arguments=part["arguments"] or "{}",
            )
            for _, part in sorted(parts.items())
            if part["name"]
        ]
        text = held.text
        parsed_from_text = False
        if not calls:
            text, calls = parse_text_tool_calls(text)
            parsed_from_text = bool(calls)
        if not calls:
            held.release()
        return LLMReply(
            text=text,
            model=model,
            latency_ms=int((time.perf_counter() - started) * 1000),
            tool_calls=calls,
            parsed_from_text=parsed_from_text,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMReply:
        started = time.perf_counter()
        try:
            response = await self._client.chat.completions.create(**self._kwargs(messages, tools))
        except openai.APIError as exc:
            raise self._error(exc) from exc

        latency_ms = int((time.perf_counter() - started) * 1000)
        message = response.choices[0].message
        calls: list[ToolCall] = []
        for raw in message.tool_calls or []:
            function = getattr(raw, "function", None)
            if function is None:
                continue
            calls.append(
                ToolCall(
                    id=raw.id or f"call_{uuid.uuid4().hex[:12]}",
                    name=function.name,
                    arguments=function.arguments or "{}",
                )
            )

        text = message.content or ""
        parsed_from_text = False
        if not calls:
            text, calls = parse_text_tool_calls(text)
            parsed_from_text = bool(calls)

        usage = getattr(response, "usage", None)
        return LLMReply(
            text=text,
            model=cast(str, response.model or self._provider.model),
            latency_ms=latency_ms,
            tool_calls=calls,
            parsed_from_text=parsed_from_text,
            prompt_tokens=int(getattr(usage, "prompt_tokens", 0) or 0),
            completion_tokens=int(getattr(usage, "completion_tokens", 0) or 0),
        )

    async def check(self) -> str | None:
        """Return a warning if the server is down or the model is missing, else None."""
        try:
            models = await self._client.models.list()
        except openai.APIConnectionError:
            return f"Can't reach {self._provider.base_url}. Start Ollama, then try again."
        except openai.APIError:
            return None  # some servers do not implement /models; the first real call will tell
        names = {item.id for item in models.data}
        wanted = self._provider.model
        if wanted not in names and f"{wanted}:latest" not in names:
            return f"Model '{wanted}' is not installed. See docs/SETUP.md (ollama create ...)."
        return None

    async def aclose(self) -> None:
        await self._client.close()


_MAYBE_CALL = ("{", "<", "`")


class _HoldBack:
    """Passes reply text on as it streams, except text that might be a tool call."""

    def __init__(self, on_text: Callable[[str], None]) -> None:
        self._on_text = on_text
        self.text = ""
        self._sent = 0
        self._holding = False

    def add(self, delta: str) -> None:
        self.text += delta
        if self._holding:
            return
        if not self.text.strip():
            return
        if self.text.lstrip().startswith(_MAYBE_CALL):
            self._holding = True
            return
        fresh = self.text[self._sent :]
        cut = fresh.find("<")
        if cut >= 0:
            self._holding = True
            fresh = fresh[:cut]
        if fresh:
            self._sent += len(fresh)
            self._on_text(fresh)

    def stop(self) -> None:
        """A tool call is coming: hold everything from here on, for good."""
        self._holding = True
        self._sent = -1

    def release(self) -> None:
        """The reply had no call after all: hand over what was held."""
        if self._sent >= 0 and self._sent < len(self.text):
            rest, self._sent = self.text[self._sent :], len(self.text)
            self._on_text(rest)
