# Roadmap

Jarvis is built in phases. Each phase ends with a stop: you test it on your laptop, and the next phase starts only after you sign off. Design is in [ARCHITECTURE.md](ARCHITECTURE.md), tradeoffs in [DECISIONS.md](DECISIONS.md), and known weak spots in [RISKS.md](RISKS.md).

## Status

| Phase | Name | Status | Version |
|---|---|---|---|
| 0 | Planning, docs, repository | Done | v0.0.1 |
| 1 | Skeleton: config, model client, agent loop, registry, audit, CLI | On `main` | v0.1.0 |
| 2 | Voice: push-to-talk, then wake word | On `main` | v0.2.0 |
| 3 | App index, VS Code, Docker, files | On `main` | v0.3.0 |
| 4 | Data APIs, fetch_page, system tools | Built on `phase/4-data-system`, waiting for your test | v0.4.0 |
| 5 | Web UI with live tool log and confirm buttons | Built on `phase/5-web-ui` (stacked on Phase 4), waiting for your test | v0.5.0 |
| 6 | UI automation, Playwright, WhatsApp | Built on `phase/6-ui-whatsapp` (stacked on Phase 5), waiting for your test | v0.6.0 |
| 7 | Notifications (feasibility spike first) | Built on `phase/7-notifications` (stacked on Phase 6), waiting for your test | v0.7.0 |
| 8 | Model router, memory, tray, startup, packaging | Built on `phase/8-router-tray` (stacked on Phase 7), waiting for your test | v0.8.0 |
| 9 | Test hardening, docs, demo (plus the Claude Code bridge, Brave, calls) | Built on `phase/9-hardening` (stacked on Phase 8), waiting for your test | v1.0.0 |
| 10 | Dictation and media | Built on `phase/10-dictation-media` (stacked on Phase 9), waiting for your test | v1.1.0 |
| 11 | Mail and calendar | Built on `phase/11-calendar-mail` (stacked on Phase 10), waiting for your test | v1.2.0 |
| 12 | MCP servers (GitHub first) | Built on `phase/12-mcp` (stacked on Phase 11), waiting for your test | v1.3.0 |
| 13 | Faster and smaller | Built on `phase/13-faster` (stacked on Phase 12), waiting for your test | v1.4.0 |
| 14 | Memory by meaning, morning briefing | Built on `phase/14-memory-briefing` (stacked on Phase 13), waiting for your test | v1.5.0 |

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

## Beyond 1.0

Ideas from [RESEARCH.md](RESEARCH.md), in the order they would pay off. Each would be a phase of its own, with its decisions asked first.

| Phase | Name | What |
|---|---|---|
| 10 | Dictation and media | built (above) |
| 11 | Calendar and mail | built (above) |
| 12 | MCP client | built (above) |
| 13 | Faster and smaller | built (above) |
| 14 | Memory by meaning | built (above) |
| 15 | Screen reading | Windows OCR where UI Automation sees nothing |
