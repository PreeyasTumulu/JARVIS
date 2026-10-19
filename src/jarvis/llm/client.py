"""One client for every model: any OpenAI-compatible endpoint (Ollama locally, Groq and
OpenRouter in the cloud)."""

from __future__ import annotations

import time
import uuid
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

    async def complete(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
    ) -> LLMReply:
        started = time.perf_counter()
        kwargs: dict[str, Any] = {
            "model": self._provider.model,
            "messages": messages,
            "temperature": self._provider.temperature,
        }
        if self._provider.max_tokens:
            kwargs["max_tokens"] = self._provider.max_tokens
        if tools:
            kwargs["tools"] = tools
        try:
            response = await self._client.chat.completions.create(**kwargs)
        except openai.APIConnectionError as exc:
            raise LLMError(
                f"I can't reach the model server at {self._provider.base_url}. Is Ollama running?"
            ) from exc
        except openai.NotFoundError as exc:
            raise LLMError(
                f"The model '{self._provider.model}' was not found. "
                "See docs/SETUP.md for the ollama create command."
            ) from exc
        except openai.APIStatusError as exc:
            raise LLMError(f"The model server returned an error ({exc.status_code}).") from exc

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
        if not calls and "<tool_call>" in text:
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
