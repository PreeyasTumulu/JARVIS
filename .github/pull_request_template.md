## What and why

<!-- What this changes, and the problem it solves. Link the issue if there is one. -->

## Checklist

- [ ] New tools have a typed signature, a docstring, a risk floor, a sensitivity label (private unless clearly public), and unit tests with mocks.
- [ ] Safety lives in the policy gate, not only in a prompt; config can tighten risk, never loosen it.
- [ ] Nothing private (messages, notifications, files, clipboard, screen text, mail, calendar) can reach a cloud model.
- [ ] Content read by tools is treated as data, never instructions.
- [ ] `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy`, and `uv run pytest` pass.
- [ ] Design choices with tradeoffs are in docs/DECISIONS.md; Windows quirks are in docs/RISKS.md.
- [ ] No em or en dashes (`uv run python scripts/check_dashes.py`).

## How I tested it

<!-- The commands you ran, and what you said to Jarvis, if it is user-facing. -->
