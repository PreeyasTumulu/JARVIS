"""Arithmetic without a model or an app: "what's 10 + 10" is answered in a millisecond.

`spoken_math` turns a request like "what is 15 percent of 240" into an expression, or returns
None when anything in it is not arithmetic, so the fast path only takes plain sums. `evaluate`
walks the expression's syntax tree and allows numbers, the four operations, powers, modulo,
and square roots. Nothing is ever passed to `eval`.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from collections.abc import Callable

from jarvis.tools.base import Risk, Sensitivity, ToolContext, ToolError, ToolResult
from jarvis.tools.registry import tool
from jarvis.voice.phrases import strip_wake_word

_PREFIX = re.compile(
    r"^(?:(?:hey |ok |okay )?jarvis,? )?(?:please )?"
    r"(?:what(?:'s| is|s)|how much is|calculate|compute|evaluate|work out|solve)?\s*",
)
_SUFFIX = re.compile(r"\s*(?:please)?\s*(?:equals?|is equal to)?\s*[?.!]*\s*$")
_WORDS: tuple[tuple[str, str], ...] = (
    (r"\bto the power of\b|\braised to\b|\bpower\b", "**"),
    (r"\bmultiplied by\b|\btimes\b|\binto\b", "*"),
    (r"\bdivided by\b|\bover\b", "/"),
    (r"\bplus\b|\band\b", "+"),
    (r"\bminus\b|\bless\b", "-"),
    (r"\bsquared\b", "**2"),
    (r"\bcubed\b", "**3"),
    (r"\b(?:the )?square root of\b", "sqrt "),
    (r"(?:%| percent) of\b", "/100*"),
    (r"%|\bpercent\b", "/100"),
    (r"\bmod(?:ulo)?\b", "%"),  # after the percent rules, which would turn it into /100
)
_ALLOWED = re.compile(r"^[\d\s.+\-*/%()]*(?:sqrt[\d\s.+\-*/%()]*)*$")
_OPERATOR = re.compile(r"[+\-*/%]|sqrt")

_BINARY: dict[type[ast.operator], Callable[[float, float], float]] = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_UNARY: dict[type[ast.unaryop], Callable[[float], float]] = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}
_TIMES_SIGN = chr(0xD7)  # the multiplication sign a phone keyboard types
_DIVIDE_SIGN = chr(0xF7)
_MAX_EXPONENT = 1000
_MAX_RESULT = 1e100


def spoken_math(text: str) -> str | None:
    """The arithmetic expression in a request, or None if the request is anything else."""
    phrase = strip_wake_word(text).casefold().strip()
    phrase = _SUFFIX.sub("", _PREFIX.sub("", phrase, count=1))
    phrase = phrase.replace(_TIMES_SIGN, "*").replace(_DIVIDE_SIGN, "/").replace("^", "**")
    phrase = re.sub(r"(?<=\d),(?=\d{3}\b)", "", phrase)  # 1,000
    phrase = re.sub(r"(?<=\d)\s*x\s*(?=[\d(])", "*", phrase)  # 3 x 4
    for pattern, replacement in _WORDS:
        phrase = re.sub(pattern, replacement, phrase)
    phrase = re.sub(r"sqrt\s*([\d.]+)", r"sqrt(\1)", phrase)
    phrase = " ".join(phrase.split())
    if not phrase or not re.search(r"\d", phrase) or not _OPERATOR.search(phrase):
        return None
    if not _ALLOWED.match(phrase):
        return None
    try:
        evaluate(phrase)
    except (ToolError, SyntaxError):
        return None
    return phrase


def evaluate(expression: str) -> float:
    """The value of an arithmetic expression. Raises ToolError for anything that is not one."""
    try:
        tree = ast.parse(expression.replace("^", "**"), mode="eval")
    except SyntaxError as exc:
        raise ToolError(f"'{expression}' is not a sum I can work out.") from exc
    return _value(tree.body)


def _value(node: ast.expr) -> float:
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        number: float = node.value  # type: ignore[assignment]  # checked on the line above
        return number
    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_value(node.operand))
    if isinstance(node, ast.BinOp) and type(node.op) in _BINARY:
        left, right = _value(node.left), _value(node.right)
        if isinstance(node.op, ast.Pow) and abs(right) > _MAX_EXPONENT:
            raise ToolError("That number is too big to work out.")
        try:
            result = _BINARY[type(node.op)](left, right)
        except ZeroDivisionError as exc:
            raise ToolError("You can't divide by zero.") from exc
        except OverflowError as exc:
            raise ToolError("That number is too big to work out.") from exc
        if isinstance(result, complex) or abs(result) > _MAX_RESULT:
            raise ToolError("That has no plain answer.")
        return result
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "sqrt"
        and len(node.args) == 1
        and not node.keywords
    ):
        inner = _value(node.args[0])
        if inner < 0:
            raise ToolError("A negative number has no real square root.")
        return math.sqrt(inner)
    raise ToolError("That is not a sum I can work out.")


def spoken_number(value: float) -> str:
    """20, not 20.0; 0.333333, not 0.33333333333; 1e+20 for the very large."""
    if isinstance(value, int) or (abs(value) < 1e15 and float(value).is_integer()):
        return str(int(value))
    return f"{value:.6g}"


@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=5)
async def calculate(ctx: ToolContext, expression: str) -> ToolResult:
    """Work out arithmetic exactly, without opening an app. Use it for any sum, percentage,
    power, or square root instead of doing the math yourself.

    Args:
        expression: The sum with + - * / % ** and sqrt(), for example "15/100*240" or "2**10".
    """
    value = evaluate(expression)
    answer = spoken_number(value)
    return ToolResult.success({"expression": expression, "value": answer}, speech=answer)
