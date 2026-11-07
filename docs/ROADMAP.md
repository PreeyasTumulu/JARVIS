# Roadmap

Jarvis is built in phases. Each phase ends with a stop: you test it on your laptop, and the next phase starts only after you sign off. Design is in [ARCHITECTURE.md](ARCHITECTURE.md), tradeoffs in [DECISIONS.md](DECISIONS.md), and known weak spots in [RISKS.md](RISKS.md).

## Status

| Phase | Name | Status | Version |
|---|---|---|---|
| 0 | Planning, docs, repository | Done | v0.0.1 |
| 1 | Skeleton: config, model client, agent loop, registry, audit, CLI | On `main` | v0.1.0 |
| 2 | Voice: push-to-talk, then wake word | On `main` | v0.2.0 |
| 3 | App index, VS Code, Docker, files | On `main` | v0.3.0 |
| 4 | Data APIs, fetch_page, system tools | On `main`, not tagged, waiting for your test | v0.4.0 |
| 5 | Web UI with live tool log and confirm buttons | On `main`, not tagged, waiting for your test | v0.5.0 |
| 6 | UI automation, Playwright, WhatsApp | On `main`, not tagged, waiting for your test | v0.6.0 |
| 7 | Notifications (feasibility spike first) | On `main`, not tagged, waiting for your test | v0.7.0 |
| 8 | Model router, memory, tray, startup, packaging | On `main`, not tagged, waiting for your test | v0.8.0 |
| 9 | Test hardening, docs, demo (plus the Claude Code bridge, Brave, calls) | On `main`, not tagged, waiting for your test | v1.0.0 |
| 10 | Dictation and media | On `main`, not tagged, waiting for your test | v1.1.0 |
| 11 | Mail and calendar | On `main`, not tagged, waiting for your test | v1.2.0 |
| 12 | MCP servers (GitHub first) | On `main`, not tagged, waiting for your test | v1.3.0 |
| 13 | Faster and smaller | On `main`, not tagged, waiting for your test | v1.4.0 |
| 14 | Memory by meaning, morning briefing | On `main`, not tagged, waiting for your test | v1.5.0 |
| 15 | Screen reading (Windows OCR) | On `main`, not tagged, waiting for your test | v1.6.0 |
| 16 | Release polish (installer, changelog, templates) | On `main`, not tagged, waiting for your test | unreleased |
| 17 | WhatsApp calls | On `main`, not tagged, waiting for your test | v1.7.0 |
| 18 | New interface and wake overlay | On `main`, not tagged, waiting for your test | v1.8.0 |
| 19 | Privacy: history expiry, forgetting, quiet when locked | Built on `phase/19-privacy` (from `main`), waiting for your test | v1.9.0 |
| 20 | Clipboard history and focus sessions | Built on `phase/20-clipboard-focus` (stacked on Phase 19), hand tested, two items need you | v1.10.0 |
| 21 | Speed and coverage: arithmetic without the model | Built on `phase/21-speed-coverage` (stacked on Phase 20), hand tested | v1.11.0 |
| 22 | Remove the page and overlay | Built on `phase/22-remove-ui` (stacked on Phase 21), hand tested | v1.12.0 |
| 23 | Research: other assistants | On `phase/23-research` (stacked on Phase 22), docs only | v1.12.0 |
| 24 | Core on LangGraph and ChromaDB | Built on `phase/24-core` (stacked on Phase 23), hand tested on scratch data | v1.13.0 |
| 25 | Jarvis as an MCP server | Built on `phase/25-mcp-server` (stacked on Phase 24), hand tested on scratch data | v1.14.0 |
| 26 | Apps, files, and office | Built on `phase/26-apps-files-office` (stacked on Phase 25), hand tested on scratch data and the real desktop | v1.15.0 |
| 27 | Music, developer tools, browser | Built on `phase/27-music-dev-browser` (stacked on Phase 26), git hand tested live; Spotify, Docker, SSH need your setup | v1.16.0 |
| 28 | Screen understanding and daily news | Built on `phase/28-vision-news` (stacked on Phase 27), hand tested with real models and feeds | v1.17.0 |
| 29 | Your phone, for free | Built on `phase/29-phone-bridge` (stacked on Phase 28), hand tested on this laptop; pairing the phone needs you | v1.18.0 |
| 30 | UI demos, then the chosen chat | Built on `phase/30-ui-demos` (stacked on Phase 29), checked in the browser; the real microphone needs you | v1.20.0 |

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

**Decisions:** STT model size and CPU vs GPU, hotkeys, voice choice, Piper vs Kokoro default. Resolved with defaults you can change in `config/local.toml`: ADR-020 (voice defaults), ADR-021 (Kokoro moves to Phase 8), ADR-022 (voice and keyboard confirmations).

**Test commands**

```powershell
uv sync --extra voice --extra piper
uv run jarvis setup-voice
uv run python scripts/voice_selftest.py --agent
uv run jarvis voice
uv run jarvis voice --wake
```

**Verified during the build (with synthesized speech, not a person talking):** the "hey jarvis" model fires about 50 ms after the phrase with a score of 0.99, Silero VAD notices the end of a command 0.8 s after it, Whisper `small.en` transcribes it exactly in about 1.3 s, and the agent then opens Notepad and Piper speaks the reply. End of speech to text ready: about 2.1 s.

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

**Decisions:** install Everything (voidtools) for fast file search, or stay with the built-in index. Resolved: no install needed. Jarvis uses Everything automatically if `es.exe` is present, and its own SQLite index otherwise (ADR-023).

**Test commands**

```powershell
uv run jarvis index
uv run jarvis ask "what docker containers are running"
uv run jarvis ask "find my resume"
uv run jarvis ask "read the readme of my jarvis project and tell me in one sentence what it is"
uv run jarvis ask "open the calculator"
uv run jarvis ask "close the calculator"
uv run python scripts/benchmark_tools.py --models jarvis-hermes3 --out docs/benchmarks/phase3.md
```

**Verified during the build (live, on this laptop):** 332 apps and 20,059 files indexed in 8 s; file search in about 6 ms; spoken names resolve correctly ("vs code", "docker", "whatsapp", "brave"); Calculator opened, focused, and closed (close in 265 ms, no prompt because it is on the safe list); Notepad brought to the front from a background process; Docker containers listed; the Jarvis README found and summarized in one sentence; a Notepad window with unsaved changes is detected from its title. Not exercised live, on purpose: stopping or starting your containers, opening files from Explorer selections, and opening files in VS Code (all covered by tests with fakes).

**Measured:** with all 16 tools, Hermes 3 8B picked the right first tool for 80% of 30 benchmark commands; keyword tool routing raised that to 87% ([phase3.md](benchmarks/phase3.md), [phase3-all-tools.md](benchmarks/phase3-all-tools.md)). Wrong first calls usually recover inside the turn, because invalid arguments and unknown names come back to the model as errors.

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

**Decisions:** which API keys you want to register (all have free tiers). Resolved: none are required. Without keys Jarvis uses yfinance, CoinGecko's public API, Frankfurter, and Open-Meteo; any key you add to `.env` is picked up automatically (ADR-028). The exfiltration rule (ADR-029) tightens safety and was added during the build.

**Test commands**

```powershell
uv sync
uv run jarvis ask "what's Reliance trading at"
uv run jarvis ask "price of Apple"
uv run jarvis ask "bitcoin in rupees"
uv run jarvis ask "convert 100 dollars to rupees"
uv run jarvis ask "what's the weather tomorrow in Hyderabad"
uv run jarvis ask "summarize https://www.python.org/about/"
uv run jarvis ask "set the volume to 30"
uv run jarvis ask "take a screenshot"
uv run jarvis chat        # then: "set a timer for 1 minute", and wait for it
uv run python scripts/benchmark_tools.py --models jarvis-hermes3 --out docs/benchmarks/phase4.md
```

Set your city once in `config/local.toml` so "weather tomorrow" works without naming it:

```toml
[weather]
home = "Hyderabad"
```

**Verified during the build (live, on this laptop):** "what's Reliance trading at" (Reliance Industries at 1,174.60 rupees, up 0.7 percent), "price of Apple", "how is the nifty doing" (spoken in points, not rupees), "bitcoin in rupees" (in lakh rupees), "convert 100 dollars to rupees", and "weather tomorrow in Hyderabad" each answered in one or two sentences, 9 to 11 s end to end; asking for Apple twice within a minute answered the second time from the cache in 1 ms (`cache hit quote:AAPL` in the log, no network request); with the network blocked (a dead proxy) the stock, currency, and weather questions all said the internet is unreachable instead of failing; a page summary came back in three sentences in 6.5 s; `localhost` was blocked; volume to 30, "a bit louder", and brightness to 70 worked and were restored; clipboard round trip with non-English text; a screenshot in 0.19 s; a reminder set, listed, and cancelled by name; a 5 second timer announced itself while `jarvis chat` waited for input. Not exercised live, on purpose: locking the screen (covered by tests).

**Measured:** with 31 tools, Hermes 3 8B picked the right first tool for 89% of 45 benchmark commands with keyword routing (all 15 Phase 4 commands correct) and 67% when it saw every tool ([phase4.md](benchmarks/phase4.md), [phase4-all-tools.md](benchmarks/phase4-all-tools.md)). The remaining misses are older vague commands ("bring up the calculator", "start docker"). "Close the calculator" makes the model return an empty reply; the agent now asks once more and recovers it (ADR-034).

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

**Decisions:** none needed asking. The design follows ADR-011; the details are ADR-035 and ADR-036.

**Test commands**

```powershell
uv sync --extra voice --extra piper
uv run jarvis serve                 # opens http://127.0.0.1:8765/?token=... in your browser
uv run jarvis serve --wake          # also listen for "Hey Jarvis"
uv run jarvis serve --no-voice      # the page only, no microphone or hotkeys
uv run pytest tests/unit/test_server.py
```

In the page, try "what's the price of Apple", then "open paint" (not on the app allowlist, so a card asks; Jarvis also asks aloud, and whichever you answer first wins), then a long command and Esc. Hold `Ctrl+Alt+J` and speak while the page is open: the spoken command, its tool calls, and the reply appear in the page.

**Verified during the build (live, on this laptop, in a browser):** the page loaded the earlier conversation from the database; "what's the price of Apple" typed in the page showed the tool chip, the Activity entry, and the reply; "open paint" showed a Confirm card with a countdown while voice asked the same question aloud, and Cancel closed the card ("Cancelled (web)"), left Paint closed, and returned voice to Ready; Esc during a page summary showed "Stopped."; the Audit log tab listed the last 45 tool calls; the layout works at phone width. Against the running server: a WebSocket from another origin and one without an Origin got HTTP 403, the page's own origin upgraded (101), a foreign Host header got 400, and the port did not answer on the laptop's network address. Not exercised live, on purpose: the mic button and a spoken command, which would record your room (both use the same code path as the push-to-talk hotkey, covered by tests).

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

**Decisions (yours, ADR-037):** accept the WhatsApp risk and send through Web first with the desktop app as fallback; step tools for the browser; contacts by hand plus vCard import; no vision fallback yet. Details: ADR-038 to ADR-043. Two changes from the plan: UI Automation goes through comtypes instead of pywinauto, and PyAutoGUI is not used (ADR-041); Jarvis's browser is Edge, because Playwright's Chromium does not start on this Windows build (ADR-040, RISKS.md R23).

**Test commands**

```powershell
uv sync --extra voice --extra piper
uv run jarvis ask "type hello world in Notepad"
uv run jarvis ask "press ctrl s in notepad"
uv run jarvis ask "what does the notepad window say"
uv run jarvis ask "search amazon.in for wireless earbuds in your browser"
uv run jarvis contacts add "Amma" "+91 98765 43210" --alias Mom
uv run jarvis contacts add "Ravi Kumar" "+91 90000 00001" --alias Ravi
uv run jarvis contacts add "Ravi Teja" "+91 90000 00002" --alias Ravi
uv run jarvis chat                  # then: message Mom that I'll be late (answer n, then y)
uv run jarvis whatsapp login        # optional: link WhatsApp Web, which also confirms delivery
uv run jarvis audit --last 5
uv run pytest -m browser            # the real-browser tests, in Edge
```

Use real contacts for the sends you want to go out. Try "tell Ravi the meeting moved" to see the "which Ravi?" question, and stay silent once to see the 30 second timeout. In `uv run jarvis serve`, the Contacts tab adds, removes, and imports contacts.

**Verified during the build (live, on this laptop, with Hermes 3 8B):** "type hello world in Notepad" typed into a Notepad tab of a test file (12 ms per character; the first try, before pacing, came out as "hello ddddd", see RISKS.md R6), and "press ctrl s in notepad" saved it, with "hello world" in the file on disk; in a test window with real Windows controls, Unicode text (Hindi, emoji, symbols) typed exactly, the password box was detected, a button and a checkbox were pressed, "click Say hello" asked first (the window belongs to PowerShell, a terminal) and pressed after yes, and "what does the Jarvis UI Test window say" read back the new status; "open wikipedia.org in your browser and search it for Hyderabad" landed on the article in 6 s and "search amazon.in for noise cancelling headphones" on Amazon's results in 3.7 s, in Edge; contacts were added from the CLI and the web page (a duplicate name and a number without a country code were refused with a reason); "message Mom that I'll be late" read back "Send this WhatsApp message to Amma (number ending 1111): "I'll be late"", and "n" sent nothing; "tell Ravi that the meeting moved to 5" asked which of the two Ravis, then confirmed the chosen one; silence timed out after 30 s; the audit log shows `denied` and `timeout`; WhatsApp Web loads in Jarvis's Edge and its QR selector matches the real page. Not exercised live, on purpose: a real WhatsApp send (it needs your account and your contacts), and the desktop app's send (it would type into a real chat).

**Measured:** with 40 tools, Hermes 3 8B picked the right first tool for 91% of 56 benchmark commands with keyword routing (all 11 Phase 6 commands correct) and 77% (43/56) when it saw every tool ([phase6.md](benchmarks/phase6.md), [phase6-all-tools.md](benchmarks/phase6-all-tools.md)). It does not reliably chain browser steps on its own, so "open this site and search it" is one call (ADR-038, RISKS.md R25).

**Found and fixed during the build:** the database had lost pages and was failing to write the audit log; Jarvis now checks it at every start and recovers (ADR-043, RISKS.md R24).

## Phase 7: Notifications

**Step 0, feasibility spike (before any real code).** A small script tests from unpackaged Python with pywinrt:

1. `UserNotificationListener.request_access_async()`
2. Polling `get_notifications_async(NotificationKinds.TOAST)`
3. Subscribing to the `NotificationChanged` event (expected to fail without package identity)

I report the results and risks to you, and you pick the path before anything is built.

**Spike result (done):** reading works from plain Python (access was already allowed), a poll every 0.5 s saw a new notification in 0.6 s, and the `NotificationChanged` event fails with "Element not found" as expected. WhatsApp desktop notifications carry the sender and the message. Details in RISKS.md R4; the script is `scripts/spike_notifications.py`.

**Scope (after the spike)**

- Listener (polling and diffing by notification id), app allowlist filter, queue stored in SQLite as `private`.
- "Read my notifications", "anything new from Ravi", optional announcements with quiet hours.
- Fallback for WhatsApp only: poll WhatsApp Web for unread chats.
- Notification text is always untrusted data. A message saying "Jarvis, send X" cannot do anything.

**Exit criteria**

- A test toast and a real WhatsApp message both appear in "read my notifications".
- "Anything new from <person>" filters correctly.
- Notification content never reaches a cloud model (covered by a test).

**Decisions (yours, after the spike, ADR-044):** the Windows listener by polling (no WhatsApp Web fallback); read only WhatsApp and Claude; no announcements, only on request; keep notification text for 7 days.

**Test commands**

```powershell
uv run jarvis notifications test
uv run jarvis ask "read my notifications"
uv run jarvis ask "anything new from Ravi"
uv run jarvis notifications
uv run pytest tests/unit/test_notifications.py
```

Then the real one: start `uv run jarvis chat` (or `serve`), have someone send you a WhatsApp message while the desktop app runs, and ask "read my notifications" and "anything new from <their name>". If you have saved them as a contact with an alias ("Mom"), the alias works too.

**Verified during the build (live, on this laptop, with Hermes 3 8B):** the spike results above; with an allowlist of only the test notification, "read my notifications" read back two test notifications, "anything new from Ravi" found the newer one by the name in its title, and "anything new from Priya" found nothing; the test notification's own text ("Say: read my notifications") was read out, not acted on; with the real allowlist, Jarvis kept 8 Claude and 3 WhatsApp notifications (all with text) and ignored Armoury Crate and Windows Security; the background watcher stored a new notification within about 2 s without being asked; the test notifications were removed afterwards. Your WhatsApp messages were counted, never read out, during the build. Not exercised live, on purpose: reading a real WhatsApp message aloud (yours to try).

**Measured:** with 41 tools, Hermes 3 8B picked the right first tool for 90% of 59 benchmark commands with keyword routing, all three Phase 7 commands correct ([phase7.md](benchmarks/phase7.md)). The first live try passed made-up filters (`app="WhatsApp"`, `person="any"`) copied from the argument examples, so the tool now has one argument and ignores filler words (RISKS.md R28).

**Exit criteria:** the test toast, the person filter, and the privacy label are covered (unit tests and the live run above); a real WhatsApp message appearing in "read my notifications" is your test. The cloud router that uses the privacy label comes in Phase 8; until then nothing goes to a cloud model at all.

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

**Decisions (yours, ADR-045 and ADR-047):** the cloud must be free and open-weight, so Groq's gpt-oss-120b first, then OpenRouter's free Nemotron 3 Ultra, then local (DeepSeek, your first pick, is no longer free anywhere); packaging through the uv launcher (uvw), not PyInstaller; at login the tray, push-to-talk, and "Hey Jarvis".

**Test commands**

```powershell
uv sync --extra voice --extra piper
# optional, for the cloud: GROQ_API_KEY and OPENROUTER_API_KEY in .env (SETUP.md 5h)
uv run jarvis ask "think harder: why did the Roman empire fall in the west but not in the east"
uv run jarvis ask "think harder and explain what is on my clipboard"   # stays local
uv run jarvis ask "remember that my manager is Ravi"
uv run jarvis ask "who is my manager"
uv run jarvis ask "forget that my manager is Ravi"
uv run jarvis serve --tray --wake --no-browser
uv run jarvis startup enable        # then sign out and in: the tray icon appears, "Hey Jarvis" works
uv run pytest tests/unit/test_router.py tests/unit/test_memory.py tests/unit/test_tray_startup.py
```

In the console, the line before each reply names the model that answered (`openai/gpt-oss-120b` for Groq, `jarvis-hermes3` for local).

**Verified during the build (live, on this laptop, with Hermes 3 8B):** without cloud keys a "think harder" question was answered locally with no delay; "remember that my manager is Ravi" saved the fact, "what do you remember about me" listed it, and "forget that my manager is Ravi" asked first and kept it on "n" (all in a separate test data folder); "who is my manager" answered "Ravi" after the fix below; `uvw run ... pythonw -m jarvis serve --tray` started with no console window, served the page, and logged "Tray icon shown"; `jarvis startup enable`, `status`, and `disable` wrote, read, and removed a working shortcut (in a scratch folder; your Startup folder is untouched). Not exercised live: a real cloud call (it needs your free Groq and OpenRouter keys), clicking the tray menu (covered by tests), and the wake word at login (it would keep the microphone on).

**Measured:** with 44 tools, Hermes 3 8B picked the right first tool for 89% of 62 benchmark commands with keyword routing, all three memory commands correct ([phase8.md](benchmarks/phase8.md)).

**Found and fixed during the build:** asked "who is my manager", the local model searched the web, once with the remembered fact as the query, sending it to DuckDuckGo. Memories are now offered before web search and count as private content, and `web_search` and `open_url` are now `egress` tools, as ADR-029 always said `open_url` was (ADR-046, RISKS.md R31).

**Exit criteria:** cloud routing for public questions and "private stays local" are proven by tests with a fake cloud that records everything it is sent (`test_router.py`); a real cloud answer needs your keys. "Starts at login into the tray and is ready to listen" is in place (`jarvis startup enable`); signing in once is your test.

## Phase 9: Hardening, docs, demo

**Scope (as planned)**

- Unit tests for every tool with mocks, and coverage reported in CI.
- Scripted e2e command suite (YAML): fake LLM in CI, real Ollama locally.
- Final pass on README, architecture, and setup. A troubleshooting guide.
- `docs/DEMO.md` demo script and a recorded demo.

**Also asked for during the phase (2026-10-20):** test every phase end to end and fix what fails; make "Hey Jarvis" work; Jarvis should use Brave only; research similar projects and new features; calling ("call my mom", "Jarvis calls me"); Claude Code asking you through Jarvis.

**Built**

- `tests/e2e/scenarios.yaml`: 41 commands across every phase with what must happen and what must never happen, run through the real pipeline with Windows, the network, WhatsApp, and the cloud faked. CI runs them scripted; `pytest tests/e2e -m llm` runs them with the real model.
- Coverage in CI (76%), failing below 75%.
- "Hey Jarvis" at login: voice failures are logged and retried, a crashed voice loop restarts, a silent microphone stream is reopened, Whisper loads offline, a hung startup dumps its stacks, and `jarvis voice --wake-test` shows the level and score live (R33, R34).
- The database corruption found and fixed: SQLite's WAL-reset bug, avoided with the rollback journal (ADR-048).
- Brave: the browser follows your default; yours is pinned to Brave (ADR-049).
- `search_site` for "search YouTube for ...", "look up ... on Wikipedia" (ADR-050).
- The Claude Code bridge: questions and permissions by voice or on the page, notices aloud, phone escalation by ntfy or Twilio when you are away (ADR-051, ADR-052).
- `call_contact`: "call mom" through Phone Link and your own phone, always after a yes (ADR-053).
- Secret values hidden in what the clipboard, windows, files, and container logs show the model (R38).
- `[server] speak_replies`: answers to typed commands are spoken too (on for you).
- Docs: [TROUBLESHOOTING.md](TROUBLESHOOTING.md), [DEMO.md](DEMO.md), [RESEARCH.md](RESEARCH.md), CONTRIBUTING.md, SECURITY.md, and updated README, architecture, setup, decisions, and risks.

**Test commands**

```powershell
uv sync --extra voice --extra piper
uv run pytest                                   # unit tests and the scripted e2e suite (about 550)
uv run pytest tests/e2e -m llm                  # the same 41 scenarios with the real model (about 4 min)
uv run pytest -m browser                        # real-browser tests, in Brave
uv run python scripts/benchmark_tools.py        # tool-choice accuracy (docs/benchmarks/phase9.md)
uv run jarvis voice --wake-test 30              # say "Hey Jarvis"; look for WAKE
uv run jarvis ask "search youtube for lofi music"
uv run jarvis ask "what's the weather tomorrow in Bangalore"
uv run jarvis ask "call mom"                    # needs the contact and Phone Link; answer n to just see the question
uv run jarvis claude-hook test                  # Jarvis asks a test question; answer by voice or on the page
uv run jarvis claude-hook install               # then Claude Code asks you through Jarvis
```

**Verified during the build (live, on this laptop):** all unit and scripted e2e tests; the 41 scenarios with Hermes 3 8B (41 of 41, after the fixes below); real APIs for weather, currency, crypto, and NSE shares; timers and memory; opening and closing Notepad; typing into and reading a scratch Notepad file; a real Groq answer in 0.8 s; private turns staying local; the web UI over its WebSocket, including refusing a foreign origin; a test notification read back with other apps excluded; the real-browser tests in Brave; the voice pipeline on synthetic speech (wake word 0.99, text 2.4 s after the end of speech); the bridge end to end (the real hook, the real server, an answer from the page: a question answered "SQLite", a permission denied); the database switched to the rollback journal; the login shortcut starting Jarvis with voice and the bridge.

**Measured:** with 46 tools, Hermes 3 8B picked the right first tool for 91% of 67 benchmark commands with keyword routing (89% of 62 in Phase 8), median 2.7 s ([phase9.md](benchmarks/phase9.md)).

**Found and fixed during the build**

| Found | Fix |
|---|---|
| Voice silently failed at login, so "Hey Jarvis" never worked | logged, retried, restarted, reopened (R33) |
| `jarvis.db` damaged twice | the WAL-reset bug; rollback journal (ADR-048) |
| "Who is my manager" saved the fact again instead of answering | questions about a memory only get `list_memories` |
| Weather recited every field and took 14 s | results with a summary ask for one or two sentences (3.5 s now) |
| "Bangalore" was a part of Karachi | old city names map to new ones; real cities rank first |
| A copied `.env` reached the model's context with its keys | secret-looking values are hidden (R38) |
| "Search youtube for ..." became a web search; "open wikipedia and search ..." dropped the search | `search_site`, and site names routed only to it |
| A tool got the word "null" for an optional argument | null words mean None |
| "What does Notepad say" recited every tab and button (35 s) | long lists ask for a short reply |
| Notifications kept from an app stayed readable after it was removed from the list | they are deleted at the next read |

**Not done, needs you:** the recorded demo video (the script is ready); a real WhatsApp send and a real WhatsApp notification (Phases 6 and 7); a real call through Phone Link; installing the Claude Code hooks; trying ntfy or Twilio (accounts). The open decisions are at the end of [DECISIONS.md](DECISIONS.md).

**Exit criteria:** every tool has unit tests with mocks and CI reports coverage; the YAML suite runs scripted in CI and against Ollama locally; the docs and the troubleshooting guide are current; the demo script exists. The recorded demo is yours to make.

## Phase 10: Dictation and media

**Scope:** hold a hotkey to dictate into any app; play, pause, and skip whatever is playing, and say what it is.

**Decisions (asked 2026-10-20, all as recommended):** short dictation typed, long dictation pasted with the clipboard restored (ADR-054); rules only, no model, for cleaning up dictated text (ADR-054); Windows media sessions with the media keys as a fallback (ADR-055); exact short phrases skip the model (ADR-056).

**Built**

- Dictation: hold `Ctrl+Alt+D`, speak, release, and the text appears where the cursor is. Whisper runs without the command hint; "new line", "new paragraph", "comma", "full stop", "question mark", "exclamation mark", "semicolon", and a final "period" become punctuation; "um" and "uh" are dropped. Up to 200 characters are typed; longer text is pasted through the clipboard, which is kept out of Win+V history and put back. A new line is Shift+Enter, so a chat message is never sent by accident. Held modifier keys and administrator windows are refused, out loud. The agent never sees dictated text.
- `media_control(action)`: play, pause, toggle, next, previous on the current Windows media session (Spotify, Media Player, YouTube in Brave), with the media keys for apps that have none. "Pause" with nothing playing presses nothing.
- `now_playing()`: the title, artist, and app (private).
- The fast path: "pause the music", "resume", "next song", "skip this song", "previous track", "what's playing", and similar exact phrases run without the model, through the policy gate and the audit log, in about 30 ms.
- `[dictation]` settings; 3 new end-to-end scenarios (44 in all), 4 new benchmark commands (71).

**Test commands**

```powershell
uv sync --extra voice --extra piper
uv run pytest                                   # about 625 tests, including the scripted e2e suite
uv run pytest tests/e2e -m llm                  # the 44 scenarios with the real model
uv run jarvis serve --wake                      # then, in Notepad or a chat box: hold Ctrl+Alt+D and say
                                                #   "hello comma new line this is a test full stop"
uv run jarvis ask "pause the music"             # with Spotify or YouTube playing
uv run jarvis ask "what's playing"
uv run jarvis ask "could you skip to the next track"
```

**Verified during the build (live, on this laptop):** dictation into a scratch window, typed (with the Shift+Enter line break) and pasted, with the clipboard identical afterwards; synthetic speech through the real Whisper in dictation mode and the rules; a silent test file in the Media Player paused, resumed, and named through media sessions; "play", "what's playing", "pause the music", and "hey jarvis pause it please" through `jarvis ask` on the fast path (about 33 ms each), and "could you resume the music for me" through Hermes 3 8B (0.9 s); the 44 scenarios with the real model.

**Measured:** Hermes 3 8B picked the right first tool for 92% of 71 commands (91% of 67 in Phase 9), median 2.8 s, all four media commands right after the `media_control` description said that "resume" means play ([phase10.md](benchmarks/phase10.md)). In the same run with every pulled model, `llama3.2:3b` scored 86% at a median of 0.4 s, fully on the GPU: a candidate for Phase 13.

**Found and fixed during the build**

| Found | Fix |
|---|---|
| "comma new line" lost the line break | spoken commands no longer swallow a line break next to them |
| "we should, uh, ship it" kept a stray comma | a filler takes the comma before it |
| "take the next line of code" became a line break | only "new line" is a command |
| Text typed while Ctrl was still held would act as shortcuts | Jarvis waits up to two seconds, then refuses and says so |
| "Resume the song" picked toggle | the tool description says resume means play |

**Not done, needs you:** dictation and media with your own voice and your own player (Spotify or YouTube in Brave).

**Exit criteria:** dictation lands in any normal app with the clipboard intact; media commands work in your player; exact phrases answer instantly.

## Phase 11: Mail and calendar

**Scope:** read your inbox and your calendar; reply to an email only after your yes.

**Decisions (asked 2026-10-20, all as recommended):** IMAP and SMTP with a Gmail app password, and the calendar from its secret iCal link, instead of Google's APIs (ADR-057); replies are sent after your yes, only to the people on that email (ADR-058); headers first, an email's full text only when you ask for it (ADR-058).

**Built**

- `read_mail(sender?, unread_only?)`: the newest emails (five by default) with sender, subject, and a short preview; "emails from Mom" uses your contacts' aliases. The folder is opened read-only, so nothing is ever marked as read.
- `read_email(message)`: one email in full, found by its number in the last list, "the second one", a sender, or subject words; quoted history removed, secret-looking values hidden, attachments named.
- `reply_email(message, text, reply_all?)`: risk floor `confirm`. The confirmation reads every address and the exact text; recipients come only from the email itself (Reply-To or the sender, plus the others for reply-all, never you); threaded with `Re:`, `In-Reply-To`, and `References`; an optional `[mail] signature`. "Reply that ..." left in the text by the model is removed.
- `calendar_events(day?)`: today, tomorrow, a weekday, this week, next week, a date, or the next event, with repeating events expanded and all-day events first; titles and places are private and untrusted.
- `jarvis mail test` and `jarvis calendar test` check the setup and print counts only; `[mail]` and `[calendar]` settings; `MAIL_APP_PASSWORD` and `CALENDAR_ICS_URL` in `.env`.
- 5 new end-to-end scenarios (49 in all), including an email that tries to get itself answered; 7 new benchmark commands (78).

**Test commands**

```powershell
uv sync --extra voice --extra piper
uv run pytest                                   # about 680 tests
uv run pytest tests/e2e -m llm                  # the 49 scenarios with the real model
uv run jarvis mail test                         # after SETUP.md 5k: counts only
uv run jarvis calendar test
uv run jarvis ask "any new email?"
uv run jarvis ask "read the second one"         # in chat or voice, right after the list
uv run jarvis ask "reply to Ravi's email saying I'll send it tonight"   # answer n to just hear the question
uv run jarvis ask "what's on my calendar today"
uv run jarvis ask "what's my next meeting"
```

**Verified during the build:** all unit tests and scripted scenarios; the 5 new scenarios with Hermes 3 8B; IMAP parsing against canned server replies (read-only EXAMINE, `BODY.PEEK` only, flags before or after the literal, HTML mail, encoded names, attachments); the calendar against a real Google iCal feed (India's public holidays: today's holiday, next week's, and 8 November's Diwali found on the right days). Not verified live: your own inbox, sending a real reply, and your own calendar, which need your app password and link.

**Measured:** Hermes 3 8B picked the right first tool for 92% of 78 commands, median 2.8 s, all seven mail and calendar commands right ([phase11.md](benchmarks/phase11.md)).

**Found and fixed during the build**

| Found | Fix |
|---|---|
| "Any new email" made up a sender (the description's example name) | the description says to leave the sender out unless the user names one |
| Hermes sometimes wrapped arguments in the call itself (`{"function": ..., "arguments": {...}}`) | the registry unwraps them for every tool |
| The reply text kept the instruction ("reply that I'll send ...") | a lead-in like "reply that" or "tell him" is removed; "Say hi to everyone" is kept |
| "Announce that the meeting starts" offered calendar tools | the calendar keywords need "my meeting", "next meeting", "meetings tomorrow", and so on |
| HTML mail came out one word per line | block tags end lines, inline tags do not |

**Not done, needs you:** an app password and the calendar link (SETUP.md 5k), then the test commands above with your own inbox and calendar.

**Exit criteria:** the inbox and calendar answer correctly by voice; nothing is marked read; a reply goes only after your yes, to the right people, in the right thread.

## Phase 12: MCP servers (GitHub first)

**Scope:** use tools from MCP servers (GitHub, Home Assistant, anything that speaks the Model Context Protocol), each through the same policy gate, privacy labels, and audit log as a built-in tool.

**Decisions (asked 2026-10-20, all as recommended):** MCP tools ask first unless the server marks them read-only and you marked the server trusted (ADR-059); only the tools you list reach the model (ADR-059); GitHub's official server first (ADR-060).

**Built**

- An MCP client on the official `mcp` SDK: `[mcp.servers.<name>]` with a `command` over stdio or a `url` over Streamable HTTP, secrets as `$NAME` from `.env` (a server without them is skipped), one task per server, connected when `jarvis serve` starts or on the first command; a broken server is logged (`logs/mcp-<name>.log`) and left out.
- Listed tools become `<server>_<tool>` Jarvis tools: risk floor `confirm`, safe only for read-only tools on a `trusted` server, `risk` per tool and `safety.tool_risk_overrides` can only raise; private (configurable) and untrusted; open-world tools are egress. The confirmation reads the server, the action, and the arguments ("GitHub: issue write (owner: PreeyasTumulu; repo: JARVIS; title: ...)").
- They are offered only when a request mentions the server's name or keywords, and never as part of "all tools". Schemas are compacted, and `[mcp.servers.<name>.params]` lists the parameters the model sees.
- GitHub: the official server in Docker (pinned v2.0.2) with ten tools, eight read-only and two that write. `jarvis mcp list`, `jarvis mcp tools <server>`, `jarvis mcp test <server>`; `scripts/benchmark_tools.py --mcp`.
- A small MCP test server (`tests/fixtures/mcp_notes_server.py`) that the tests start over stdio: 20 MCP tests and 2 end-to-end scenarios (51 in all) run the real SDK, transport, and policy gate.

**Test commands**

```powershell
uv sync --extra voice --extra piper
uv run pytest                                   # about 700 tests (the MCP ones start a real server)
docker pull ghcr.io/github/github-mcp-server:v2.0.2
uv run jarvis mcp list                          # after GITHUB_PERSONAL_ACCESS_TOKEN is in .env
uv run jarvis mcp test github                   # the ten tools and whether each asks first
uv run jarvis ask "remember that my GitHub username is PreeyasTumulu"
uv run jarvis ask "any open issues on my JARVIS repo on github"
uv run jarvis ask "what were the last commits on JARVIS"
uv run jarvis ask "open a github issue on JARVIS titled test from Jarvis"   # answer n to just hear the question
```

**Verified during the build (live, on this laptop):** the MCP SDK's stdio transport on Windows against the test server (listing, read-only and writing tools, errors, an unlisted tool kept hidden, a broken command, a missing secret); GitHub's official server started in Docker, listing its 46 tools and exposing the ten configured ones with the right risk (with a placeholder token: listing needs no real one, so no GitHub API call was made); `jarvis mcp list` and `jarvis mcp test github`. Not verified live: a real GitHub call, which needs your token.

**Measured:** with GitHub's ten tools added, Hermes 3 8B picked the right first tool for 92% of 86 commands, and all eight GitHub commands right ([phase12.md](benchmarks/phase12.md)). Before trimming, GitHub's schemas were 19,000 characters, requests took 6 to 17 seconds, and one timed out after 69 seconds; trimmed (6,700 characters), GitHub requests take 5 to 9 seconds. This run's overall median (4.3 s, 2.8 s in Phase 11) is not comparable: a game was running with 1 GB of memory free, and the same run without MCP was 4.3 s too.

**Found and fixed during the build**

| Found | Fix |
|---|---|
| GitHub's full schemas made requests 3 to 5 times slower and one time out | compacted schemas and per-tool `params` |
| Compacting dropped GitHub's `title` parameter (schema titles and a parameter called title look alike) | parameter names are never touched |
| Plain results came back as `{"result": ...}` | unwrapped |
| `jarvis mcp test` without the token said no tools exist | it names the missing secret |
| Under pythonw a server's log had nowhere to go | each server logs to `logs/mcp-<name>.log` |

**Not done, needs you:** a GitHub token in `.env`, Docker Desktop running, and the test commands above; any other server you want (Home Assistant example in SETUP.md 5l).

**Exit criteria:** GitHub questions are answered by voice; reading runs, writing asks; a broken or missing server never affects the rest of Jarvis.

## Phase 13: Faster and smaller

**Scope:** a smaller default model if the benchmark agrees, routing that understands paraphrases, and faster speech recognition.

**Decisions (asked 2026-10-20, all as recommended):** download qwen3:4b to compare; switch the default only for a model within 3 points of Hermes, twice as fast, and safe (ADR-061); measure Whisper and switch only if accuracy holds (ADR-062); embeddings as a routing backup (ADR-063).

**Built**

- Semantic routing: a request with none of the keywords is matched by meaning (`nomic-embed-text`) to the right tool groups instead of getting all 52 tools; keywords still decide when they match, and failures fall back silently. Warmed up when `jarvis serve` starts.
- Whisper on the GPU (`stt_device = "auto"` with the new `gpu` extra), checked by a real warm-up transcription and falling back to the CPU on any failure.
- `scripts/benchmark_stt.py` (Whisper models, synthetic speech or `--record` / `--mine` for your own voice) and `--no-semantic` for the tool benchmark; six paraphrase commands added (84 in all).
- `config/ollama/qwen3-4b.Modelfile` for Qwen3 4B Instruct, kept as an option.

**Measured** ([phase13.md](benchmarks/phase13.md), [stt.md](benchmarks/stt.md), [stt-gpu.md](benchmarks/stt-gpu.md))

| | Right first tool (84) | Median | Placement |
|---|---|---|---|
| Hermes 3 8B, semantic routing | 93% | 2.7 s | 58% CPU |
| Hermes 3 8B, keywords only | 86% | 2.8 s | 58% CPU |
| Llama 3.2 3B, semantic routing | 87% | 0.4 s | GPU |
| Qwen3 4B Instruct, semantic routing | 86% | 1.4 s | 34% CPU |

| Whisper (30 spoken commands, Piper voice with noise) | Word error rate | Median |
|---|---|---|
| small.en, GPU | 6.8% | 135 ms |
| base.en, GPU | 7.7% | 56 ms |
| small.en, CPU (before) | 11.2% | 1,434 ms |
| base.en, CPU | 8.0% | 442 ms |
| distil-small.en, CPU | 17.4% | 1,304 ms |

The voice self-test went from 2.2 s to 0.97 s between the end of speech and the text being ready, and Hermes keeps its GPU share and its 1.0 s warm replies with Whisper and the embedding model loaded. Hermes stays the default: both small models are 6 or more points behind.

**Test commands**

```powershell
uv sync --extra voice --extra piper --extra gpu
uv run pytest                                   # about 715 tests
uv run python scripts/voice_selftest.py         # "heard ... in about 130 ms"
uv run jarvis ask "what have I got lined up tomorrow"     # the calendar, not a web search
uv run jarvis ask "it's too loud, bring it down"          # the volume
uv run python scripts/benchmark_stt.py --record           # read 30 commands once
uv run python scripts/benchmark_stt.py --mine --device cuda --models small.en base.en medium.en
```

**Found and fixed during the build**

| Found | Fix |
|---|---|
| `qwen3:4b` is now the thinking-only release; nothing turns its reasoning off | benchmarked Qwen3 4B Instruct 2507 instead |
| Whisper on the GPU failed on a missing cuBLAS DLL | the `gpu` extra, with its DLL folders added to the search path |
| The warm-up never ran the model (faster-whisper's segments are lazy), so the first command paid the GPU start | the warm-up consumes the segments |
| Paraphrases got every tool and often a web search or no tool | semantic routing |

**Not done, needs you:** reading the 30 commands once in your own voice (`--record`), to confirm small.en against base.en or medium.en for your accent and microphone.

**Exit criteria:** commands are understood faster with no loss of accuracy; paraphrases reach the right tools; Hermes's speed holds with everything loaded.

## Phase 14: Memory by meaning and the morning briefing

**Scope:** find memories and past commands by meaning; a short spoken briefing for the day.

**Decisions (asked 2026-10-20, all as recommended):** memories and past commands, both by meaning (ADR-065); a briefing of weather, calendar and reminders, and unread email and messages, offered once a day and played only after a yes (ADR-066).

**Built**

- `core/meaning.py`: embeddings from `nomic-embed-text` kept in a new `embeddings` table, computed once per item and dropped with it; words as the fallback.
- Memories that fit each request are found by meaning across all of them (up to 500 kept) and repeated next to the request for the model.
- `recall(about, when?)`: what you asked and what Jarvis answered, by meaning, within today, yesterday, this or last week or month, a weekday, a date, or "N days ago". Questions about your own past requests are offered only recall, so the model cannot reach for the topic's tool instead.
- `briefing()`: weather for `weather.home`, today's events and reminders, unread email count with senders, new messages with senders; every part with its own timeout and left out quietly when it is not set up. "Good morning", "brief me", and "how does my day look" run it without the model; the first command of the morning offers it, and a plain yes plays it.
- 2 new end-to-end scenarios (53 in all), 3 new benchmark commands (87).

**Test commands**

```powershell
uv run pytest                                   # about 750 tests
uv run jarvis ask "good morning"                # after [weather] home = "Hyderabad" in local.toml
uv run jarvis ask "remember that my manager is Ravi"
uv run jarvis ask "who is my boss"              # found by meaning, not shared words
uv run jarvis ask "what did I ask about the weather earlier"
```

**Verified during the build (live, with a scratch data folder):** "brief me" gave Hyderabad's weather, today's holiday from a public Google calendar, and a test reminder in 2.4 s with no model; recall answered "what did I ask about music today" and "when did I ask about the weather" from real earlier commands, with their times; the two new scenarios with Hermes 3 8B. Memory matching thresholds were measured with the real embedding model: unrelated requests scored at most 0.49, real matches 0.52 to 0.77.

**Measured:** Hermes 3 8B picked the right first tool for 93% of 87 commands, median 2.7 s, all three new ones right ([phase14.md](benchmarks/phase14.md)).

**Found and fixed during the build**

| Found | Fix |
|---|---|
| "When did I last ask about the weather" called the weather tool, and a Docker recall question got no tool | questions about your own past requests are offered only recall |
| "Earlier" was not a recall word, so the model answered from nothing | added, with a prompt rule never to guess an earlier request |
| Forgetting the last memory left its vector behind | vectors are synced even when no memory is left |
| A command recorded in the same millisecond as the search was missed | the time range includes its end |
| The briefing offer could repeat when two clocks disagreed | one clock decides the day |

**Not done, needs you:** `[weather] home` in local.toml for the briefing's weather; the Phase 11 setup for its calendar and email.

**Exit criteria:** "good morning" gives a useful briefing; past commands and memories are found by meaning.

## Phase 15: Screen reading

**Scope:** read and click in apps that show Windows nothing (games, some Electron apps, images, remote desktop), and read the whole screen.

**Decisions (asked 2026-10-20, all as recommended):** OCR as an automatic fallback; OCR clicks always ask first; the window, or the whole screen when asked (ADR-067).

**Built**

- `platform/ocr.py`: a window's pixels (its DWM bounds) or every screen captured with mss and read by Windows' own OCR (`Windows.Media.Ocr`), each word with its position; fuzzy finding of a phrase with a rival check.
- `read_window_text` falls back to OCR when UI Automation sees fewer than 40 characters, bringing the window forward first.
- `click` falls back to clicking the centre of the text on screen, always after a yes, finding it again just before the click.
- `read_screen()` for "what's on my screen". Private and untrusted, secrets hidden.
- `[ui] ocr_fallback` and `ocr_min_chars`; 11 OCR tests, 1 new scenario (54 in all), 2 new benchmark commands (89).

**Test commands**

```powershell
uv run pytest                                   # about 765 tests
uv run jarvis ask "what's on my screen"
uv run jarvis ask "what does <a game or canvas app> say"
uv run jarvis ask "click <a button's text> in <that app>"   # asks first, then clicks
```

**Verified during the build (live, on a scratch window that shows UI Automation nothing):** `read_window_text` fell back to OCR and read every line; "click save draft" asked first and the click landed at the exact centre of the button; reading the whole screen took 0.33 s (60 lines, not printed). Windows OCR languages here: English (GB and US).

**Measured:** Hermes 3 8B 93% of 89 commands, median 2.7 s, both screen commands right ([phase15.md](benchmarks/phase15.md)).

**Found and fixed during the build**

| Found | Fix |
|---|---|
| "What's on my screen" also offered the calendar ("what's on") | the calendar phrase no longer matches the screen |
| OCR read "12" as "1 2" | phrases are matched fuzzily and by words, so near misses still match |

**Not done, needs you:** try it on a real app that shows no text (a game launcher, a canvas app, a remote desktop window).

**Exit criteria:** apps that hide their text can be read and, with your yes, clicked.

## Phase 16: Release polish

**Scope:** the open-source polish recommended after Phase 15: a one-command installer, a changelog, contribution templates, and a release process. Built without questions, on the recommendations, as asked.

**Built**

- `install.ps1`: checks and sets up everything (uv, Ollama, Python packages with GPU speech recognition when possible, the models, config files from templates, speech models), asking before any winget install; `-DryRun`, `-NoVoice`, `-NonInteractive`, `-Model`. CI runs the dry run.
- CHANGELOG.md with every phase as a version (0.0.1 to 1.6.0).
- Issue templates (bug report with version, area, and a reminder to leave private content out; feature request with a safety question), a pull request template with the project's rules as a checklist, CODEOWNERS, and Dependabot for GitHub Actions.
- docs/RELEASING.md: merging the stacked phases into `main` and tagging, after the review.
- The README quick start is now the installer.

**Test commands**

```powershell
.\install.ps1 -DryRun                           # reports what would run, changes nothing
.\install.ps1                                   # the real thing; safe to run again
uv run pytest
```

**Verified during the build:** the dry run on this laptop (every check right: Windows 11, uv, Ollama 0.40.6, the RTX 3050, the downloaded models, the existing config files kept); a real non-interactive run (packages synced with the GPU extra, speech models confirmed, config untouched).

**Not done, needs you:** the GitHub release and tags, after your review (docs/RELEASING.md); README screenshots and the demo video, which need your screen.

**Exit criteria:** a new user gets from clone to "Hey Jarvis" with one command plus SETUP.md for accounts.

## Phase 17: WhatsApp calls

**Scope:** "call mom" rings them on WhatsApp, and "hang up" ends the call.

**Decisions (asked 2026-10-31):** the WhatsApp desktop app instead of Phone Link, which stays available by a setting (ADR-069).

**Built**

- `call_contact` opens the chat with a one-time marker, checks that it arrived, clears it, and presses Voice call. It reports honestly whether the call was seen starting.
- `hang_up`, `[calls] method`, and `scripts/spike_whatsapp_call.py`, a read-only check of the call buttons that hides personal text.
- Also fixed: desktop WhatsApp sends never pressed Send, because the web view reports its host pane as focused. Reading the focused field inside the window fixed it, confirmed by a real send.

**Test commands**

```powershell
uv run pytest tests/unit/test_calls.py tests/unit/test_uia_focus.py
uv run python scripts/spike_whatsapp_call.py    # with a chat open; presses nothing
uv run jarvis ask "call single"                 # someone who expects it; answer yes
uv run jarvis ask "hang up"
```

**Verified during the build (live, on this laptop):** the Voice call button seen as one enabled button with one on-screen position in an open chat; the message box read 8 times out of 8 with WhatsApp in front; a real message sent by you through the fixed check. Not verified live: the marker being cleared, a real call, the name of the end call button, and how a call looks to Windows.

**Measured:** Hermes 3 8B 91% of 90 commands, median 3.0 s ([phase17.md](benchmarks/phase17.md)). Both call commands were right, but bare "hang up" got no tool, so exact phrases now take the fast path; "hang up" was then checked live and reaches `hang_up`.

**Checked on 2026-11-02, on separate test data with a made-up contact:** answering no places no call, an unknown name is refused before any question, and "hang up" with no call on says so and presses nothing. A real call is still not verified.

**Not done, needs a real call first:** pausing "Hey Jarvis" during a call, which depends on detecting the call (R52).

**Exit criteria:** "call <contact>" rings the right person after a yes; a chat that fails to open places no call; "hang up" ends the call.

## Phase 18: New interface and wake overlay

**Scope:** when you say "Hey Jarvis", the whole screen changes, not only a page, and your words appear as you say them. A new page to match, using tasteskill.

**Decisions (asked 2026-11-01, all as recommended):** a reactor with plasma edges; the full screen while you speak, then an edge glow; confirmations by voice or the page; hidden from captures, with a setting for demos (ADR-071). Native OpenGL over a web view, after measuring both (ADR-070).

**Built**

- `jarvis.overlay`: a separate process with a transparent window that takes no clicks and no focus, driven over a pipe; `jarvis overlay demo`; `[overlay]` settings.
- `reactor.glsl`, one shader for the overlay and the page: domain-warped plasma, a wake shockwave with a split-colour front, and a reactor with lightning, coils, and voice bars.
- Live transcripts and a voice level while recording (ADR-072).
- The page rebuilt (ADR-073), with every feature kept: confirmations, questions, tool log, audit log, contacts, mic, stop.

**Test commands**

```powershell
# Close any running Jarvis first: uv cannot replace jarvis.exe while it runs.
uv sync --extra voice --extra piper --extra gpu
uv run jarvis overlay demo                      # the whole effect, about 20 seconds; nothing recorded or run
uv run jarvis serve --wake                      # then say "Hey Jarvis, what's the weather tomorrow"
uv run pytest tests/unit/test_overlay.py tests/unit/test_voice_live.py
```

Try it with a light window open, say a command that opens an app (it should recede so you can watch), and "message <someone> that ..." and answer no (amber, with the exact question).

**Verified during the build (live, on this laptop):** the overlay process against a test window, reading only that window's pixels: transparent with a smooth falloff, clicks pass through, never the foreground window, hidden from capture, first light 65 ms after the message, gone after hiding, exits when the pipe closes; hidden 0% CPU and visible about 21% of one core; 2 to 4 ms of GPU time a frame on the AMD GPU at 1080p. Synthetic speech through real Whisper on the GPU, the real agent with Hermes 3 8B, and the real overlay process: three partials in 3.3 s of speech and the final text 190 ms after it ended. Every overlay state judged from frames rendered over a made-up desktop, never your real screen. The page in a browser with made-up events: conversation, wake takeover, and the amber confirmation with its card clear; tasteskill's inspector at 1440, 768, and 390 with 0 FAIL. Not verified live: your own voice and microphone, the wake word actually opening it, a fullscreen game, a second monitor, and sleep and resume.

**Found and fixed during the build**

| Found | Fix |
|---|---|
| WebView2 could not be transparent | a native OpenGL window (ADR-070) |
| A layered window with no attributes stays invisible, and "fully transparent" passed anyway | set the attributes, and test the falloff, not just one pixel |
| The fullscreen check used 5 for presentation mode, which is the normal desktop, so the overlay never showed | 4, with a comment |
| Waiting for vsync spun 58% of a core in the driver | no vsync on a composited window, frames paced with a sleep: 21% |
| The plasma showed a picture frame, with creases from the corners | a soft minimum of the four edges |
| The receded glow fogged the whole desktop | a thin line unless the screen is dark |
| Light added to a white window was lost, so the small core vanished | a dark backing behind it |
| Streaks fell across the conversation while idle | only while active |
| A new confirmation card focused Confirm, so a stray Enter or Space could approve it (there since Phase 5) | it focuses Cancel; Confirm takes a click or Tab |
| After a no, the model could say "they said no", as if the other person had refused | the refusal says who answered and gives the exact reply |
| A cancelled tool showed "failed" in the conversation | it shows "cancelled" |
| "Hey Jarvis" kept listening on a locked PC, and a spoken yes approves things | the microphone closes while locked (ADR-074, R55) |

**Not done, needs you:** the test commands above with your own voice, restarting your running Jarvis first. A wider test on a real fullscreen game.

**Exit criteria:** "Hey Jarvis" transforms the whole screen with no focus lost and clicks still working; your words appear as you speak; it recedes while Jarvis works and leaves no trace when done.

## Phase 19: Privacy

**Goal:** what Jarvis keeps has an end date, you can delete it by voice, and a locked PC says nothing private.

**Scope**

- `[history] keep_days` (90) and `audit_keep_days` (365); `storage/retention.py` runs at start and once a day (ADR-075).
- `forget_history(about, when)`: confirm floor; matches words in the command or its answer; takes vectors and audit rows; the conversation is cleared and the request is not kept.
- Locked PC: speech cut off, reminders held until you unlock, answers left on the page, `speak` refuses (ADR-076).

**Test it**

1. "what's the weather", then "forget what I asked about the weather". It asks first, says how many, and "what did I ask about the weather" then finds nothing.
2. Set a reminder for a minute away ("remind me in one minute to stretch") and lock the PC. It says only that something is waiting; unlock and it says the reminder.

**Not done, needs you:** both tests with a real lock. Everything here is tested with fakes.

**Exit criteria:** nothing is kept past its keep time, a forgotten command is gone from history, vectors, audit, and conversation, and a locked PC says nothing private.

## Phase 20: Clipboard history and focus sessions

**Goal:** "the second last thing I copied" works without leaving anything on disk, and a focus session keeps Jarvis quiet and then says what you missed.

**Scope**

- `clipboard_history`, `clipboard_restore`, `clipboard_forget`, off by default (ADR-077).
- `focus_start`, `focus_end`, `focus_status`; exact phrases skip the model (ADR-078).

**Test it**

1. Set `history = true` under `[clipboard]` in `config/local.toml` and restart. Copy two things, say "what did I copy earlier", then "put the second last thing I copied back on the clipboard", and press Ctrl+V.
2. "Start a focus session for 2 minutes", then "remind me in one minute to stretch". Nothing is said at one minute. At two it says the session is over, that one reminder waited, and then the reminder.

**Not done, needs you:** both tests by hand. Everything here is tested with fakes; the PC was locked during the build, and Windows refuses clipboard access then, so the real clipboard has not been read.

**Exit criteria:** nothing copied reaches the disk, a marked copy is never kept, and a reminder due during a focus session is heard after it.

## Phase 21: Speed and coverage

**Goal:** a plain sum is answered at once, without the model, and the tests cover more of the code.

**Scope**

- `calculate(expression)`: a safe evaluator over the syntax tree (numbers, + - * / % **, sqrt); nothing reaches `eval` (ADR-082).
- The fast path turns "what's 10 + 10", "15 percent of 240", "2 to the power of 10", "the square root of 144" into a `calculate` call with no model; anything else in the sentence sends it to the model, which also gets `calculate` for wordy math ("a 15 percent tip on 840").
- A bare JSON tool call from the model runs instead of being read aloud; `claude-hook` no longer loads the agent.
- Coverage floor in CI raised from 75 to 78 percent (78 measured).

**Measured:** "what's 10 + 10" answers "20" in 0 ms of tool time and no model call; a wordy tip question takes one model call (3.3 s) and gets "126". `jarvis chat` starts and quits in 2.5 s (0.66 s of it importing the CLI); startup is measured again after the LangGraph move (ADR-079) rather than tuned on the loop that is being replaced.

**Test it**

1. "what's 10 + 10": it says "20" and the log line shows no model.
2. "what's a 15 percent tip on 840 rupees": one model call, `calculate`, "126".

**Exit criteria:** plain sums never wait for the model, and the evaluator refuses anything that is not arithmetic.

## Phase 22: Remove the page and overlay

**Goal:** the core carries no UI it is about to replace; voice and `jarvis chat` work as before, and the server is a local API the next UI can use (ADR-081).

**Scope**

- Deleted: the page (`server/static`), its shader, the OpenGL wake overlay (`jarvis/overlay`), `jarvis overlay demo`, the tray's Open Jarvis item, `[overlay]`, `[server] open_browser`, and the `glfw` and `moderngl` dependencies.
- The server keeps `GET /health`, `POST /bridge`, and the WebSocket protocol; it refuses any request with an `Origin` header and needs the token from `bridge.json`.
- Started from a terminal, `jarvis serve` also takes y or n there.
- Old configs and start-at-login shortcuts keep working.
- Found while testing and fixed: Jarvis crashed on its first Piper sentence when voice was off (R58).

**Test it**

1. `uv run jarvis chat`, then "what's 10 + 10".
2. `uv run jarvis serve --no-voice`, then `curl http://127.0.0.1:8765/health`.

**Exit criteria:** nothing of the page or overlay is left in the code, voice and chat behave as before, no website can reach the API, and Jarvis does not crash when it speaks.

## Phase 23: Research

**Goal:** before the core is rebuilt, know how the strongest open-source assistants solve routing, tools, safety, memory, latency, and UI states, and what Jarvis should take or do differently.

**Done:** [RESEARCH.md](RESEARCH.md) section 6 (a table per project, what we take with the phase it lands in, where Jarvis does better, licences) and the full report with about 120 sources in [research/open-source-assistants-2026.md](research/open-source-assistants-2026.md). Four claims the next phase builds on were checked by hand against their primary source. Findings that changed the plan: Phase 24 gains a tiered router pipeline, a `handled_by` field, a guard node, named graph states, tool interruption options, streaming TTS, and a per-stage latency breakdown; R59 records the small-model tool-call risk; Piper's GPL licence is confirmed in the installed package, which keeps ADR-006 (optional, never bundled) binding on the Phase 31 installer.

**Exit criteria:** every project in the brief is covered with sources, and each "take" item names the phase that builds it.

## Phase 24: Core on LangGraph and ChromaDB

**Goal:** the agent loop is a graph whose policy gate no path can skip, obvious commands never wait for a model, and voice replies start speaking before the model has finished (ADR-079, ADR-083, ADR-084).

**Scope**

- The turn is a LangGraph graph: route, think, guard, gate, await_confirmation, execute, respond (ARCHITECTURE.md 4.1, drawn from the code and checked by a test). Every node publishes `AgentStateChanged` with a named state.
- A router pipeline before the model (`[router] pipeline`, `stage_timeout_ms`): exact phrases, sums, and one-slot templates ("open {app}" for apps in the index, "volume {n}", mute). `handled_by` on every turn in history and the audit log.
- A guard before the gate: one repair of a near-miss name or broken JSON, no repeated call in a turn, `max_tool_calls_per_turn`.
- Clearances: a tool runs only with a one-time clearance from the gate for exactly its arguments. Source scans keep every entry point behind the gate.
- `cancel_on_interruption` per tool: a send that already started finishes and is audited when it ends.
- ChromaDB for memories and past commands, copied once from SQLite, with SQLite as the fallback. Memory kinds `user` and `context` with their own budgets; vectors written after the turn.
- Streamed replies: the local model streams, text that could be a tool call is held back, and Piper speaks sentence by sentence (SAPI too). `[tts] stream`. `first_token_ms` and `first_audio_ms` join the stage times.
- `jarvis/adapters`: the web API client moved there and gained keys from .env, one retry after a timeout or a 502, 503, or 504, and logs without query strings.
- LangGraph and ChromaDB import in a warm-up thread when `chat` or `serve` starts. LangSmith tracing is forced off (R60).

**Test it**

1. `uv run jarvis chat`, then "open notepad": "Opening Notepad." with no model line (the second time on a fresh data folder, R61).
2. "what's 12 times 7": "84", no model.
3. "remember that my manager is Ravi", then "who is my boss": "Ravi".
4. `uv run jarvis voice`, push to talk, "why do cats purr": speech starts before the reply is finished.
5. `uv run pytest tests/unit/test_gate_coverage.py`.

**Measured (2026-11-07):** imports: LangGraph 2.7 s, ChromaDB 1.0 s, both off the startup path (warm-up thread, 3.0 s in the background on a cold start). Router stages: 0 to 3 ms once the app index is built. Streaming, warm model: first text after 0.9 to 1.4 s against 5.7 to 7.1 s for whole replies; first audio with real Piper (silent player) 2.8 s and 3.6 s against 3.7 s and 5.0 s for the whole reply plus the first sentence, and no gain for a reply of one long sentence. Tool choice ([benchmarks/phase24.md](benchmarks/phase24.md), the model alone, without the router stages): jarvis-hermes3 89% of 97 at a 3.0 s median (Phase 17: 91% of 90); llama3.2:3b 88% at 0.4 s.

**Exit criteria:** every tool entry point meets the gate (checked by tests), every turn says who handled it, and a streamed voice reply is never spoken twice or over a confirmation.

## Phase 25: Jarvis as an MCP server

**Goal:** other MCP clients can use Jarvis's tools without a way around its policy gate, its audit log, or its privacy rule (ADR-085). Also: Llama 3.2 3B measured as a faster default and kept as an option (ADR-086).

**Scope**

- `jarvis mcp serve`: a stdio MCP server that clients start; it lists the offered tools and forwards each call to the running `jarvis serve` with the token from `bridge.json`.
- `/mcp/` on the local API (Streamable HTTP, behind the API's checks) and `Agent.run_call`: the argument check, the gate, the clearance, and the audit, one call at a time with turns, outside the conversation.
- `[mcp_server] enabled` and `tools`; private tools are never offered whatever the list says, and each refused name is logged once.
- Confirmations name the client on every channel ("Claude Code wants to: Open Paint"); refusals reach the client in plain words.
- The live end-to-end test checks safety before the first tool choice, so a wrong tool cannot hide a leak.

**Test it**

1. `uv run jarvis serve`, then in Claude Code `claude mcp add jarvis -- uv run --directory <this folder> jarvis mcp serve`.
2. Ask Claude Code "use the jarvis calculate tool for 12 * 7": 84, and `uv run jarvis audit --last 1` shows `mcp:...`.
3. Add `open_app` to `[mcp_server] tools`, restart the client, ask it to open Paint: Jarvis asks you, naming Claude Code.

**Measured (2026-11-07):** a forwarded call takes 0.1 to 0.4 s; "Jarvis is not running" comes back in about 2 s. Models, live end-to-end suite: Hermes 3 8B 51 of 54 in 322 s, Llama 3.2 3B 50 of 54 in 95 s, both with every safety check passed; streamed first audio 2.8 to 3.6 s against 1.2 to 1.5 s.

**Exit criteria:** no private tool can be offered, every call is audited with the client's name, and nothing that needs a yes runs without one from you.

## Phase 26: Apps, files, and office

**Goal:** the everyday desk jobs from the brief: apps opened with timing or later, a file opened by name, notes, a row in a sheet, and the Calculator app (ADR-087 to ADR-090).

**Scope**

- `open_app` waits for the window and says how long it took; `schedule_app` opens or closes later, with the yes asked once when you say it (`ApprovedChannel`), the gate again when it runs, and never late.
- `open_file` takes the name as you said it ("open my resume") in one call.
- `take_note`, `read_notes`, `open_notes`; "note that ..." in the router's template stage.
- `add_sheet_row`: Excel through pywin32 (found by the running object table or the workbook window), openpyxl with a backup, CSV; always asks first and reads back.
- `calculator_show`: Scientific mode, the sum typed, the display read and checked.
- Router pipeline tests; the benchmark gained seven cases for these tools.

**Test it**

1. "open notepad": it says how long it took.
2. "close spotify in 1 minute", say yes, wait: Spotify closes and Jarvis says so.
3. "note that the plumber comes on tuesday", then "what did I note today".
4. With a budget workbook in Documents open in Excel: "add tea and 40 to my budget sheet", yes: the row appears, unsaved.
5. "show 18 percent of 2400 in the calculator".

**Measured (2026-11-07):** Calculator opened in 1.1 s and read back 432 and 4875 correctly; a scheduled open fired and ran through the gate; a note took 6 ms without the model; a row through a running Excel and through openpyxl each took 0.1 to 1.1 s. Tool choice ([benchmarks/phase26.md](benchmarks/phase26.md)): jarvis-hermes3 92% of 104, six of the seven new cases right.

**Exit criteria:** nothing is written to a file without a yes, a scheduled action never runs late or without the gate, and every answer from Calculator is checked against Jarvis's own.

## Phase 27: Music, developer tools, browser

**Goal:** the music and developer jobs from the brief: Spotify search and play, Docker with a readiness wait, SSH profiles, and git commit and push behind a yes (ADR-091 to ADR-095). Media keys and Brave site search were already done (Phases 10 and 9).

**Scope**

- `play_spotify`: search API with client credentials, the desktop app, play on Spotify's media session, and a check of what plays.
- `docker_up`: compose projects from config or images with names and ports only; readiness by health check or answering ports.
- `ssh_connect`: profiles from config, opened in Windows Terminal.
- `git_changes`, `git_commit`, `git_push`: diff for the local model, commit and push each asked.
- Timing arguments on tools that only run now are refused (ADR-095), found by the benchmark.

**Test it**

1. Add the Spotify keys, then "play snowman by wys on spotify".
2. With Docker Desktop running and a project in `[docker.projects]`: "start the shop project".
3. With a profile in `[ssh.profiles]`: "connect to my pi".
4. With a repository in `[git.repos]`: "what changed in jarvis", "commit it", "push it".

**Measured (2026-11-07):** live with the real model on a scratch repository and a local remote: the diff was read in 0.2 s, the drafted message was "Add discount feature to cart", and the commit and the push each took about 1.3 s after a yes; the remote has the commit. Phase 26 benchmark (hermes3, 104 commands with seven new ones): 92%, the miss being "open vs code at 9 tomorrow" as open_app, which led to ADR-095.

**Exit criteria:** nothing reaches a remote, a server, or Docker without your yes or your own typing, and Spotify is never said to play when it does not.

## Phase 28: Screen understanding and daily news

**Goal:** questions about the screen answered by a local vision model, and a daily AI and tech digest you can hear and keep (ADR-080, ADR-096, ADR-097).

**Scope**

- `look_at_screen`: the screenshot and Windows OCR's text to gemma3:4b on Ollama, secrets hidden, the answer marked as outside content; Hermes loaded again right after.
- `ai_news`: RSS and Atom feeds through the adapter, recent stories, the same story merged across feeds, one sentence each by a cloud model (Hermes as fallback), saved as Markdown with links; a `news` part in the briefing.
- The adapter's `get_bytes` for feeds, with the same retry, rate limit, and redaction as JSON calls.

**Test it**

1. Open something with an error message, then "what's on my screen" or "what does this error mean".
2. "What's new in AI", then open today's file in `Documents\Jarvis News`.
3. "Good morning": the briefing ends with how many AI stories there are.

**Measured (2026-11-07):** vision on a synthetic screen with real OCR and gemma3: 14.8 s cold, 22 s for a quick follow-up (the models swap), both answers right where gemma3 alone misread the year; Hermes back in memory afterwards. Digest from the four real feeds: 8 stories in 2.7 to 3.5 s with Groq, 15.7 to 16.2 s with Hermes alone. Tool choice ([benchmarks/phase28.md](benchmarks/phase28.md)): jarvis-hermes3 96 of 108 (89%) as scored; all four new cases right; two misses were expectations the new tools made out of date ("what's on my screen" now goes to look_at_screen, "latest news about OpenAI" to ai_news), now accepted. The model passed refresh=true to ai_news every time, so a digest under an hour old is read instead.

**Exit criteria:** no screenshot leaves the laptop, every digest story keeps its link, and a story without text is never filled in by the model.

## Phase 29: Your phone, for free

**Goal:** Jarvis and Claude Code can get your attention on your phone and hand it things, at no cost (ADR-098). Calls where Jarvis speaks were researched first and not built (ADR-099, RESEARCH.md 2.4).

**Scope**

- `jarvis.adapters.phone`: KDE Connect (`kdeconnect-cli`) over the Wi-Fi, ntfy pushes when the phone is away, timeouts, and errors that say how to fix them.
- `ring_phone`, `notify_phone`, `send_to_phone`; "find my phone" without the model; a `phone` routing group.
- `set_reminder(on_phone=true)` rings the phone when the reminder is due.
- The Claude Code bridge's phone step defaults to `kdeconnect`; `ring_phone` and `notify_phone` are offered to MCP clients.

**Test it**

1. Pair the phone (SETUP.md 5s), then "find my phone".
2. "Send the clipboard to my phone" (answer yes), then a file: "send my resume to my phone".
3. "Remind me on my phone in 2 minutes to stretch", and wait.
4. Leave a Claude Code question unanswered for 45 s: the phone shows it.

**Measured (2026-11-07):** KDE Connect's device list in about 2.1 s; an ntfy push in 0.75 to 0.87 s, read back from ntfy.sh with priority 5; "find my phone" handled by the exact phrase stage; Hermes set a phone reminder with `on_phone` in 8.9 s once `{"null": true}` was accepted. Tool choice: Hermes 104 of 113 (92%), all five phone commands right, and the nine misses are the same as before Phase 29 ([phase29.md](benchmarks/phase29.md)).

**Exit criteria:** nothing reaches anyone but you, a file never leaves the Wi-Fi, and a phone that cannot be reached is explained, never silently skipped.

## Phase 30: UI demos

**Goal:** see and compare how the new interface could look before building it (ADR-100).

**Scope**

- Six concepts in `ui-demos/`, each one HTML file. All of them show the seven states: idle, listening, thinking, speaking, waiting for your yes, running a tool, and error.
- One kit (`_kit.js`), copied into each page by `scripts/build_ui_demos.py`. It holds the scripted run, the state buttons and keys, the opt-in real microphone level, reduced motion, and frozen frames for screenshots.
- `scripts/capture_ui_demos.py` makes the screenshots with Playwright and Edge. An index page and `ui-demos/README.md` show them.

**Test it**

1. Double-click `ui-demos/index.html`, then open each concept and watch one full run.
2. Press `1` to `7`, answer Yes and No on the confirmation, and press Space to play the run again.
3. Press "Use my microphone", allow it, and speak: listening should follow your voice.

**Measured (2026-11-07):** all 42 states (six concepts by seven) captured and checked at 1000 by 625 and at a phone's 390 by 844. Two layout problems were found and fixed: the pill's confirmation pushed its buttons apart, and the edge glow read as a hard frame. A third fix: the terminal showed a failed tool as "ok". The 24 README screenshots come to 664 KB.

**Exit criteria:** every concept shows all seven states, opens offline with no network requests, and is checked by a test.

**The chosen direction (2026-11-07, v1.20.0):** you picked the orb and the edge glow. `ui-demos/chat.html` combines them around a conversation (ADR-101).
- **The orb:** glides from the middle into the header.
- **The edge glow:** a thin turning ring plus a soft inset bloom.
- **The conversation:** live words both ways, and confirmation cards.
- **Typing:** type, talk, or stop.
- **Themes:** light and dark, with a remembered switch.

It was checked in all seven states, light and dark, at 1000 by 680 and 390 by 844, plus a live typed run with Yes, the mic, and New chat. That found and fixed two problems: a hard inner edge in the glow, and an answered confirmation left as an empty box. Six design and animation skills were installed for it: emil-design-eng, improve-animations, choreograph, animation-performance, impeccable, and ui-ux-pro-max. review-animations is also installed, but only you can start it (`/review-animations`).

## Beyond 1.0

Ideas from [RESEARCH.md](RESEARCH.md), in the order they would pay off. Each would be a phase of its own, with its decisions asked first.

| Phase | Name | What |
|---|---|---|
| 10 | Dictation and media | built (above) |
| 11 | Calendar and mail | built (above) |
| 12 | MCP client | built (above) |
| 13 | Faster and smaller | built (above) |
| 14 | Memory by meaning | built (above) |
| 15 | Screen reading | built (above) |

## Next: the November 2026 brief

Planned on 2026-11-05 from your brief, in this order. Research comes before the core rewrite so the design can take what works elsewhere. Each phase is hand tested and logged in [HANDTESTS.md](HANDTESTS.md); anything only you can do goes on one list.

| Phase | Name | What |
|---|---|---|
| 22 | Remove the page and overlay (done) | Delete the HTML page, shader, and OpenGL overlay and their dependencies; the server stays as a JSON API; confirmations in the CLI and by voice (ADR-081) |
| 23 | Research (done) | Open Interpreter, Leon, OpenVoiceOS, Home Assistant Assist, Willow, Pipecat, LiveKit Agents, Open WebUI, strong "JARVIS" repos: architecture, plugins, UI, what users like, what is weak; "what we take, what we do better" in RESEARCH.md |
| 24 | Core on LangGraph and ChromaDB (done) | The agent loop as a LangGraph graph with the policy gate as a node it cannot skip; vectors in ChromaDB; an adapters layer (OS, apps, browser, APIs, shell, SSH, telephony), one pattern for API auth, retries, timeouts, and rate limits; from Phase 23: a tiered router pipeline with `handled_by` on every turn, a guard node (schema check, one repair, no duplicate calls, a step cap), named graph states mapped to UI states, tool options `cancel_on_interruption` and `timeout_secs`, sentence-streamed Piper, a per-stage latency breakdown, a test that every tool entry point meets the gate; ARCHITECTURE.md rewritten with diagrams (ADR-079) |
| 25 | Jarvis as an MCP server (done) | Expose Jarvis's tools to other MCP clients through the same policy gate, alongside the MCP client from Phase 12 |
| 26 | Apps, files, and office (done) | Open and close any app with timing, fuzzy file open, add a row to a sheet, Calculator app, notes in Notepad and a notes folder |
| 27 | Music, developer tools, browser (done) | Spotify search and play, media keys, Docker run with readiness wait, SSH profiles from config, git commit and push with a confirm before push, Brave site search |
| 28 | Screen understanding and daily news (done) | Local vision model (ADR-080), a morning AI and tech digest spoken and saved as Markdown with sources |
| 29 | Phone calls (done: your phone for free) | Researched cost, Indian numbers, and legal limits; you chose free alerts and file sending by KDE Connect and ntfy over paid calls (ADR-098, ADR-099) |
| 30 | UI demos (done) | Six standalone concepts in `ui-demos/` with seven states each, screenshots in the README (ADR-100) |
| 31 | Open-source readiness | Demo GIF, feature list, quickstart, `.env.example`, a check that no personal paths, servers, or contacts are committed |
