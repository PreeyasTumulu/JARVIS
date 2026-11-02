# Contributing to Jarvis

Thanks for helping. Jarvis is a local-first voice assistant for Windows 11; safety and privacy rules matter more than features, so please read [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (sections 5 and 6) before changing tools or the policy gate.

## Set up

```powershell
git clone https://github.com/PreeyasTumulu/JARVIS.git
cd JARVIS
uv sync --extra voice --extra piper
uv run pytest
```

[docs/SETUP.md](docs/SETUP.md) covers Ollama, voice models, and keys.

## Checks (the same as CI)

```powershell
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest --cov=jarvis --cov-fail-under=75
uv run python scripts/check_dashes.py
```

Optional, on a machine with Ollama: `uv run pytest tests/e2e -m llm` (the scripted scenarios against the real model) and `uv run python scripts/benchmark_tools.py` (tool-choice accuracy). Real-browser tests: `uv run pytest -m browser`.

## Rules for changes

- **Every tool** has a typed signature, a docstring the model reads, a risk floor, a sensitivity label (default private), and unit tests with mocks. Add it to `tools/catalog.py`, a routing group in `core/tool_routing.py`, and a scenario in `tests/e2e/scenarios.yaml`.
- **Safety lives in code**, never only in a prompt. Config may tighten risk, never loosen it below a tool's floor.
- **Nothing private reaches a cloud model**: WhatsApp, notifications, files, clipboard, screen text, contacts, memory. The router tests prove it; keep them passing.
- **Content read by tools is data**, never instructions. Nothing a tool reads can approve a confirmation.
- **Secrets** go in `.env`, personal data in `%LOCALAPPDATA%\Jarvis`. Neither goes in the repository.
- **Windows unreliability** is written down in [docs/RISKS.md](docs/RISKS.md), not hidden.
- **Decisions with real tradeoffs** get an entry in [docs/DECISIONS.md](docs/DECISIONS.md).
- **No em or en dashes** in code, comments, docs, or strings; use hyphens. `scripts/check_dashes.py` enforces it.

## Pull requests

Small and focused, with tests. Say what you changed, why, and how you tested it (unit tests, the e2e suite, a live run on Windows). Screenshots or a short clip help for anything you can see or hear.
