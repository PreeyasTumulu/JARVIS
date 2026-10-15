"""The @tool decorator and the registry that turns Python functions into LLM tools.

A tool is an async function `(ctx, **args) -> ToolResult`. Its signature and Google-style
docstring become the JSON schema sent to the model, and a pydantic model built from the same
signature validates whatever arguments the model sends back.
"""

from __future__ import annotations

import inspect
import re
import typing
from collections.abc import Awaitable, Callable, Iterable, Iterator
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, create_model

from jarvis.tools.base import Prepared, Risk, Sensitivity, ToolContext, ToolResult

ToolFn = Callable[..., Awaitable[ToolResult]]
PrepareFn = Callable[[ToolContext, dict[str, Any]], Awaitable[Prepared]]

_SECTION_HEADERS = {"returns", "raises", "example", "examples", "note", "notes", "yields"}
_ARG_LINE = re.compile(r"^(\s*)(\w+)(?:\s*\([^)]*\))?:\s*(.*)$")


@dataclass
class Tool:
    name: str
    description: str
    risk: Risk
    sensitivity: Sensitivity
    untrusted: bool
    timeout_s: float | None
    args_model: type[BaseModel]
    fn: ToolFn
    prepare_fn: PrepareFn | None = None
    egress: bool = False  # sends a request to an address the model chooses (see policy.py)

    def preparer(self, fn: PrepareFn) -> PrepareFn:
        """Register a side-effect-free step that resolves and risk-rates arguments."""
        self.prepare_fn = fn
        return fn

    def schema(self) -> dict[str, Any]:
        parameters = _clean_schema(self.args_model.model_json_schema())
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": parameters,
            },
        }

    def validate(self, raw: dict[str, Any]) -> dict[str, Any]:
        """Validate model-supplied arguments. Raises pydantic.ValidationError."""
        return self.args_model.model_validate(raw).model_dump()

    async def prepare(self, ctx: ToolContext, args: dict[str, Any]) -> Prepared:
        if self.prepare_fn is not None:
            return await self.prepare_fn(ctx, args)
        return Prepared(args=args, summary=describe_call(self.name, args), risk=self.risk)

    async def __call__(self, ctx: ToolContext, **kwargs: Any) -> ToolResult:
        return await self.fn(ctx, **kwargs)


def tool(
    *,
    risk: Risk,
    sensitivity: Sensitivity = Sensitivity.PRIVATE,
    untrusted: bool = False,
    timeout_s: float | None = None,
    name: str | None = None,
    egress: bool = False,
) -> Callable[[ToolFn], Tool]:
    """Turn an async function into a Tool. Sensitivity defaults to private (fail closed)."""

    def wrap(fn: ToolFn) -> Tool:
        if not inspect.iscoroutinefunction(fn):
            raise TypeError(f"Tool {fn.__name__} must be an async function")
        description, arg_docs = parse_docstring(fn.__doc__)
        if not description:
            raise ValueError(f"Tool {fn.__name__} needs a docstring; it becomes the description")
        return Tool(
            name=name or fn.__name__,
            description=description,
            risk=risk,
            sensitivity=sensitivity,
            untrusted=untrusted,
            timeout_s=timeout_s,
            args_model=_build_args_model(fn, arg_docs),
            fn=fn,
            egress=egress,
        )

    return wrap


class Registry:
    def __init__(self, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for item in tools:
            self.register(item)

    def register(self, item: Tool) -> None:
        if item.name in self._tools:
            raise ValueError(f"Tool '{item.name}' is already registered")
        self._tools[item.name] = item

    def get(self, name: str) -> Tool | None:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return list(self._tools)

    def schemas(self) -> list[dict[str, Any]]:
        return [item.schema() for item in self._tools.values()]

    def __iter__(self) -> Iterator[Tool]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)


def describe_call(name: str, args: dict[str, Any]) -> str:
    rendered = ", ".join(f"{key}={value!r}" for key, value in args.items())
    return f"{name}({rendered})"


def parse_docstring(doc: str | None) -> tuple[str, dict[str, str]]:
    """Split a Google-style docstring into (description, {arg: description})."""
    lines = inspect.cleandoc(doc or "").splitlines()
    description: list[str] = []
    args: dict[str, str] = {}
    section = "description"
    arg_indent: int | None = None
    current: str | None = None

    for line in lines:
        stripped = line.strip()
        header = stripped[:-1].lower() if stripped.endswith(":") else None
        if header in {"args", "arguments", "parameters"}:
            section, arg_indent, current = "args", None, None
            continue
        if header in _SECTION_HEADERS:
            section = "other"
            continue
        if section == "description":
            description.append(stripped)
        elif section == "args" and stripped:
            indent = len(line) - len(line.lstrip())
            match = _ARG_LINE.match(line)
            if match and (arg_indent is None or indent <= arg_indent):
                arg_indent = indent
                current = match.group(2)
                args[current] = match.group(3).strip()
            elif current is not None:
                args[current] = f"{args[current]} {stripped}".strip()

    text = " ".join(part for part in description if part)
    return text, args


def _build_args_model(fn: ToolFn, arg_docs: dict[str, str]) -> type[BaseModel]:
    hints = typing.get_type_hints(fn)
    params = list(inspect.signature(fn).parameters.values())[1:]  # first parameter is ctx
    fields: dict[str, Any] = {}
    for param in params:
        if param.kind in (param.VAR_POSITIONAL, param.VAR_KEYWORD):
            raise TypeError(f"Tool {fn.__name__} cannot use *args or **kwargs")
        default = ... if param.default is inspect.Parameter.empty else param.default
        fields[param.name] = (
            hints.get(param.name, Any),
            Field(default, description=arg_docs.get(param.name)),
        )
    model: type[BaseModel] = create_model(
        f"{fn.__name__}_args",
        __config__=ConfigDict(extra="ignore"),
        **fields,
    )
    return model


def _clean_schema(node: Any) -> Any:
    """Drop pydantic's auto-generated titles: they cost tokens and add nothing for the model."""
    if isinstance(node, dict):
        cleaned: dict[str, Any] = {}
        for key, value in node.items():
            if key == "title" and isinstance(value, str):
                continue
            if key in {"properties", "$defs"} and isinstance(value, dict):
                cleaned[key] = {name: _clean_schema(sub) for name, sub in value.items()}
            else:
                cleaned[key] = _clean_schema(value)
        return cleaned
    if isinstance(node, list):
        return [_clean_schema(item) for item in node]
    return node
