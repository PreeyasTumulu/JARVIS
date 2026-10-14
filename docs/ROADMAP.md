# Roadmap

Jarvis is built in phases. Each phase ends with a stop: you test it on your laptop, and the next phase starts only after you sign off. Design is in [ARCHITECTURE.md](ARCHITECTURE.md), tradeoffs in [DECISIONS.md](DECISIONS.md), and known weak spots in [RISKS.md](RISKS.md).

## Status

| Phase | Name | Status | Version |
|---|---|---|---|
| 0 | Planning, docs, repository | Done | v0.0.1 |
| 1 | Skeleton: config, model client, agent loop, registry, audit, CLI | Built, waiting for your test | v0.1.0 |
| 2 | Voice: push-to-talk, then wake word | Planned | v0.2.0 |
| 3 | App index, VS Code, Docker, files | Planned | v0.3.0 |
| 4 | Data APIs, fetch_page, system tools | Planned | v0.4.0 |
| 5 | Web UI with live tool log and confirm buttons | Planned | v0.5.0 |
| 6 | UI automation, Playwright, WhatsApp | Planned | v0.6.0 |
| 7 | Notifications (feasibility spike first) | Planned | v0.7.0 |
| 8 | Model router, memory, tray, startup, packaging | Planned | v0.8.0 |
| 9 | Test hardening, docs, demo | Planned | v1.0.0 |

## How each phase runs

1. Work happens on a branch named `phase/<n>-<name>`, for example `phase/1-skeleton`.
2. Small commits with clear messages. Tests are written alongside the code, not saved for Phase 9.
3. At the end of the phase I give you: what works, exact commands to test it, and known issues.
4. You test. Fixes go on the same branch.
5. When you sign off, the branch is merged to `main` and tagged.
6. Any choice with a real tradeoff, and any system-level install, is asked before it happens. Those are listed under "Decisions" in each phase.

---

## Phase 0: Planning (done)

- Verified the laptop environment (see [SETUP.md](SETUP.md)).
- Researched the risky areas: notification access, Hermes 3 tool calling in Ollama, openWakeWord on Windows, Piper licensing.
- Wrote README, architecture, roadmap, setup, decisions, and risks.
- Initialized git and the GitHub repository.

## Phase 1: Skeleton

**Goal:** typing a command in the terminal makes Jarvis plan with Hermes 3, call tools, and answer, with every tool call audited.

**Scope**

- Project tooling: `pyproject.toml` (uv), ruff, mypy, pytest, pre-commit, GitHub Actions CI on `windows-latest`, and a script that fails CI if an em or en dash appears in docs or comments.
- Config: `config/jarvis.toml` + `config/local.toml` + `.env`, typed with pydantic-settings.
- Model client: AsyncOpenAI against Ollama, `config/ollama/hermes3.Modelfile` (sets `num_ctx`), fallback parser for `<tool_call>` text.
- Tool registry: `@tool` decorator, JSON schema generation, risk and sensitivity labels, prepare and execute phases, timeouts.
- Policy gate with allowlists and a CLI confirmation prompt.
- Agent loop: max iterations, turn timeout, cancel token (Ctrl+C cancels the turn, not the app).
- SQLite with migrations: `audit_log`, `command_history`, `preferences`.
- Event bus and a rich CLI that shows tool calls live.
- Tools:
  - `open_app` (basic): Start Menu shortcuts plus `Get-StartApps` (the `shell:AppsFolder` list), fuzzy matched with rapidfuzz. The full app index comes in Phase 3.
  - `web_search`: DuckDuckGo via the `ddgs` package.
  - `speak`: through the TTS interface, using Windows SAPI for now (no extra dependency). Piper arrives in Phase 2.
  - `ask_user`.
- Benchmark script: 20 scripted commands, measuring tool-choice accuracy and latency for `hermes3:8b`, `hermes3:3b`, and the already installed `llama3.2:3b` on this laptop.

**Exit criteria (you test)**

- `uv run jarvis chat`, then "open notepad" opens Notepad.
- "search the web for the latest Python release" returns a short answer built from search results.
- "say hello" speaks out loud.
- An unlisted app asks for confirmation, and "no" cancels it.
- `uv run jarvis audit --last 10` shows every call with arguments and decisions.
- `uv run pytest` passes and CI is green.
- Benchmark results are written to `docs/benchmarks/phase1.md`.

**Test commands**

```powershell
uv sync
ollama create jarvis-hermes3 -f config/ollama/hermes3-8b.Modelfile
ollama create jarvis-hermes3-3b -f config/ollama/hermes3-3b.Modelfile
uv run jarvis chat
uv run jarvis audit --last 10
uv run pytest
uv run python scripts/benchmark_tools.py
```

**Decisions:** pull `hermes3:8b` (4.7 GB) and `hermes3:3b` (2.0 GB), then pick the default from benchmark numbers. Resolved: the 8B stays the default (ADR-018, [benchmark](benchmarks/phase1.md)).

## Phase 2: Voice

**Goal:** speak to Jarvis and hear it answer, with the same behaviour as text.

**2a. Push-to-talk**

- Audio capture with sounddevice, hold-to-talk hotkey on a dedicated hotkey thread.
- faster-whisper STT (`small.en`, CPU int8 by default).
- Piper TTS (optional extra), sentence-by-sentence playback, SAPI fallback.
- Barge-in: pressing push-to-talk while Jarvis speaks stops the speech.
- Global stop hotkey and the voice command "stop", both cancel the current turn.
- Voice confirmations: "yes" or "no" answers a pending confirmation.
- Per-stage latency recorded (STT, LLM, tools, TTS).

**2b. Wake word**

- openWakeWord "hey jarvis" (ONNX backend), Silero VAD for end of speech.
- Wake word paused while Jarvis speaks (prevents self-trigger).
- Threshold tuning and a false-trigger log.

**Exit criteria**

- Hold the hotkey, say "open notepad", release: Notepad opens and Jarvis says so.
- "Hey Jarvis, what time is it" works hands-free.
- The stop hotkey cuts off a long answer immediately.
- A typed command and the same spoken command produce the same tool calls.
- Median time from end of speech to the tool starting is measured and reported.

**Decisions:** STT model size and CPU vs GPU, hotkeys, voice choice, Piper vs Kokoro default.

## Phase 3: Apps, VS Code, Docker, files

**Goal:** open, focus, and close any installed app by name, and work with files inside your allowlist.

**Scope**

- App index: Start Menu shortcuts (all users and current user) plus packaged apps from `Get-StartApps`, stored in SQLite, refreshed on demand. Aliases ("code" means VS Code).
- `open_app`, `focus_app`, `close_app` (confirm unless the app is on the safe-to-close list).
- Adapters: VS Code (`code`, `code --goto file:line`), Docker (list, start, stop, logs, and starting Docker Desktop if it is not running), default browser.
- Files: folder allowlist with path resolution, `find_file` (Everything CLI if installed, otherwise a background index of allowlisted folders), `open_file`, `read_file` (size cap, text and PDF).
- "Open this file": the Explorer selection through `Shell.Application`, or the active VS Code editor from its window title. Otherwise Jarvis asks.

**Exit criteria**

- "Open Docker", "focus VS Code", "close Notepad" (asks first) all work.
- "Open my resume" finds the file inside allowlisted folders, asks if there are several matches, and opens it.
- "What containers are running" answers. "Stop the postgres container" asks first.
- A path outside the allowlist is blocked and shows up in the audit log as blocked.

**Decisions:** install Everything (voidtools) for fast file search, or stay with the built-in index.

## Phase 4: Data APIs and system tools

**Goal:** answer data questions from free APIs and control basic system settings.

**Scope**

- `market_data` with a configurable provider chain: Finnhub, Twelve Data, Alpha Vantage, yfinance. Indian tickers (`RELIANCE.NS`, `.BO`) go to yfinance first.
- Symbol resolution: aliases in SQLite plus provider symbol search ("Reliance" to `RELIANCE.NS`).
- Open-Meteo (weather and geocoding), Frankfurter (currency), CoinGecko (crypto).
- Caching with TTLs in SQLite, a token-bucket rate limiter per provider, and a circuit breaker that skips a provider after repeated failures.
- Spoken formatting: "Reliance is at 2,945 rupees, up 1.2 percent today."
- `fetch_page` with readable-text extraction.
- System: volume, brightness, lock screen, screenshot, clipboard read and write, timers and reminders.
- If tool-choice accuracy drops as the tool count grows, add tool retrieval with `nomic-embed-text` (already installed) to send only the relevant tools.

**Exit criteria**

- "What's Reliance trading at", "price of Apple", "bitcoin in rupees", "convert 100 dollars to rupees", "weather tomorrow" all answer in one or two spoken sentences.
- With the network off, Jarvis says the data is unavailable instead of crashing.
- A second identical question within the cache window makes no network call (visible in logs).
- "Volume to 30", "lock my laptop", "take a screenshot", "remind me in 10 minutes to stretch" work.

**Decisions:** which API keys you want to register (all have free tiers).

## Phase 5: Web UI

**Goal:** a local web page that does everything voice does.

**Scope**

- FastAPI + one WebSocket, static HTML, CSS, and JavaScript (no build step).
- Chat, live tool-call log, confirmation cards with Confirm and Cancel, mic toggle, Stop button, voice state indicator, recent audit view.
- Voice transcripts and replies appear in the same chat. One session across all channels.
- Security: bind `127.0.0.1`, check `Origin`, per-launch token.

**Exit criteria**

- `uv run jarvis serve` opens the UI. Typed commands behave exactly like the CLI and voice.
- A confirm-level action shows a card, and clicking Cancel stops it.
- A voice command made while the UI is open shows up live in the chat and the tool log.
- A WebSocket connection from another origin is rejected.

## Phase 6: UI automation, Playwright, WhatsApp

**Goal:** drive apps that have no CLI, and send WhatsApp messages safely.

**Scope**

- pywinauto (UIA) tools: `click(element)`, `type_text`, `press_keys`, `read_window_text`, all on the COM worker thread. PyAutoGUI as the last resort. Vision fallback behind a flag, off by default.
- Playwright `browser_task` in a dedicated persistent profile (separate from your daily browser). Each sub-step goes through the policy gate. Submits, purchases, and password fields are confirm or blocked.
- Contacts and aliases in SQLite, with CLI and UI commands to add them. Ambiguous names trigger `ask_user`.
- `send_whatsapp`:
  - Primary: WhatsApp Web via Playwright with a persistent logged-in profile (scan the QR code once).
  - Fallback: WhatsApp desktop through the `whatsapp://send?phone=...&text=...` deep link, then press Enter after confirmation.
  - Always reads the message back and requires an explicit yes. Verifies the message appears in the chat after sending.

**Exit criteria**

- "Type hello world in Notepad" works.
- "Message Mom that I'll be late" reads it back, waits for yes, sends, and confirms delivery.
- Saying "no" or staying silent sends nothing, and the audit log shows the denial.
- An ambiguous contact name asks which one you mean.

**Decisions:** accepting the WhatsApp automation risk (see RISKS.md), and where contacts come from (manual entry first).

## Phase 7: Notifications

**Step 0, feasibility spike (before any real code).** A small script tests from unpackaged Python with pywinrt:

1. `UserNotificationListener.request_access_async()`
2. Polling `get_notifications_async(NotificationKinds.TOAST)`
3. Subscribing to the `NotificationChanged` event (expected to fail without package identity)

I report the results and risks to you, and you pick the path before anything is built.

**Scope (after the spike)**

- Listener (polling and diffing by notification id), app allowlist filter, queue stored in SQLite as `private`.
- "Read my notifications", "anything new from Ravi", optional announcements with quiet hours.
- Fallback for WhatsApp only: poll WhatsApp Web for unread chats.
- Notification text is always untrusted data. A message saying "Jarvis, send X" cannot do anything.

**Exit criteria**

- A test toast and a real WhatsApp message both appear in "read my notifications".
- "Anything new from <person>" filters correctly.
- Notification content never reaches a cloud model (covered by a test).

## Phase 8: Router, memory, tray, startup, packaging

**Scope**

- Model router with a cloud provider (for example DeepSeek through its OpenAI-compatible API), escalation by explicit request or heuristic, the privacy guard, a spend cap, and fallback to local.
- Memory: "remember that my manager is Ravi", stored locally, injected into the prompt, with "what do you remember" and "forget that".
- Tray icon: status, mic toggle, open UI, quit.
- Run on startup through a shortcut in the Startup folder (no registry edits).
- Packaging decision: a uv-based launcher vs a frozen PyInstaller build.

**Exit criteria**

- A heavy reasoning question with only public context goes to the cloud (when enabled). Any turn with private content stays local, proven by tests.
- Jarvis starts at login into the tray and is ready to listen.

**Decisions:** cloud provider and budget, packaging approach.

## Phase 9: Hardening, docs, demo

- Unit tests for every tool with mocks, and coverage reported in CI.
- Scripted e2e command suite (YAML): fake LLM in CI, real Ollama locally.
- Final pass on README, architecture, and setup. A troubleshooting guide.
- `docs/DEMO.md` demo script and a recorded demo.
