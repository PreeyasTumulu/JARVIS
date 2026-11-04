"""Arithmetic: spoken sums to expressions, a safe evaluator, and the model-free fast path."""

from __future__ import annotations

import json

import pytest

from jarvis.core.fast_path import fast_call
from jarvis.core.tool_routing import select_tools
from jarvis.tools.base import ToolError
from jarvis.tools.catalog import build_registry
from jarvis.tools.system.arithmetic import evaluate, spoken_math, spoken_number
from tests.conftest import MakeApp
from tests.unit.test_recall_briefing import call


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("what's 10 + 10", "20"),
        ("What is 10 + 10?", "20"),
        ("10+10", "20"),
        ("hey jarvis what's 7 times 8", "56"),
        ("what is 15 percent of 240", "36"),
        ("15% of 240", "36"),
        ("calculate 2 to the power of 10", "1024"),
        ("what's 2^10", "1024"),
        ("100 divided by 8", "12.5"),
        ("what's 1,000 minus 1", "999"),
        ("3 x 4", "12"),
        (f"12 {chr(0xD7)} 3", "36"),
        ("what is the square root of 144", "12"),
        ("what's 9 squared", "81"),
        ("17 mod 5", "2"),
        ("(2 + 3) * 4", "20"),
        ("-5 + 2", "-3"),
        ("1 / 3", "0.333333"),
        ("how much is 5 into 3", "15"),
        ("what's 10 + 10 please", "20"),
    ],
)
def test_spoken_sums_are_worked_out(text: str, value: str) -> None:
    expression = spoken_math(text)
    assert expression is not None, text
    assert spoken_number(evaluate(expression)) == value


@pytest.mark.parametrize(
    "text",
    [
        "what's the weather",
        "what is 7",  # no operation: not a sum
        "open docker",
        "calculate 10 + 10 in the calculator",  # the Calculator app, not the fast path
        "what's 10 + 10 dollars in rupees",
        "set a timer for 10 minutes",
        "remind me in 5 minutes",
        "what's 5 divided by 0",  # an error goes to the model, which can explain it
        "play track 2",
        "__import__('os').system('calc')",
        "2 ** 99999",
        "",
    ],
)
def test_anything_that_is_not_a_plain_sum_is_left_to_the_model(text: str) -> None:
    assert spoken_math(text) is None


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("1/0", "divide by zero"),
        ("2**5000", "too big"),
        ("sqrt(-4)", "square root"),
        ("(-8)**0.5", "no plain answer"),
        ("__import__('os')", "not a sum"),
        ("abs(-3)", "not a sum"),
        ("'a' * 3", "not a sum"),
        ("1 +", "not a sum"),
        ("10.0**300 * 10.0**300", "no plain answer"),
    ],
)
def test_the_evaluator_refuses_anything_else(expression: str, message: str) -> None:
    with pytest.raises(ToolError, match=message):
        evaluate(expression)


def test_numbers_are_said_plainly() -> None:
    assert spoken_number(20.0) == "20"
    assert spoken_number(12.5) == "12.5"
    assert spoken_number(2**60) == str(2**60)
    assert spoken_number(1e20) == "1e+20"


def test_the_fast_path_calls_calculate() -> None:
    assert fast_call("what's 10 + 10") == ("calculate", json.dumps({"expression": "10 + 10"}))
    assert fast_call("pause") == ("media_control", json.dumps({"action": "pause"}))


async def test_what_is_ten_plus_ten_needs_no_model(make_app: MakeApp) -> None:
    h = make_app()  # no scripted replies: any model call would fail the turn
    result = await h.app.agent.run_turn("what's 10 + 10")
    assert result.text == "20"
    assert h.llm.requests == []
    assert result.model == "fast path"
    (row,) = h.audit()
    assert row["tool"] == "calculate"
    assert row["decision"] == "auto"


async def test_the_tool_reports_errors_to_the_model(make_app: MakeApp) -> None:
    h = make_app()
    done = await call(h, "calculate", expression="15/100*240")
    assert done.result.ok
    assert done.result.data == {"expression": "15/100*240", "value": "36"}
    failed = await call(h, "calculate", expression="1/0")
    assert not failed.result.ok
    assert "divide by zero" in str(failed.result.error)


@pytest.mark.parametrize(
    "text", ["what's a 15 percent tip on 840", "calculate my share of 1200 split 3 ways"]
)
def test_wordy_math_offers_calculate_to_the_model(text: str) -> None:
    names = {item.name for item in select_tools(text, build_registry())}
    assert "calculate" in names
