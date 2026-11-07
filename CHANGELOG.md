# Changelog

Every phase of Jarvis, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

Versions 0.4.0 to 1.8.0 are merged to `main` with green CI, but not tagged: they wait for a hands-on test. Details, test commands, and measurements for each are in [docs/ROADMAP.md](docs/ROADMAP.md); every design decision is in [docs/DECISIONS.md](docs/DECISIONS.md).

## [Unreleased]

### Added
- The chat window is live: `jarvis serve` serves it, and `jarvis ui`, the tray's "Open Jarvis", or saying "open Jarvis" opens it in Brave's app mode. It shows typed and spoken turns, confirmations, questions, Stop, push-to-talk, and the last 20 turns. Only that page may use the socket (ADR-103).
- Open-source readiness: a demo GIF from the chat interface at the top of the README, a quickstart that starts with the offline demo pages, and a CI check that the repository holds no personal data (`scripts/check_personal.py`, ADR-102).

### Changed
- The UI demos, tests, and docs use made-up devices and addresses instead of the real ones from live tests.
- `ui-demos/chat.html`: the orb and the edge glow brought together around a conversation. The orb glides from the middle into the header, your words and Jarvis's reply appear live, confirmations are cards in the conversation, and light and dark themes are included (ADR-101).
- `ui-demos/`: six standalone UI concepts (reactor, orb, edge glow, terminal, pill, constellation). Each shows the same seven states, plays a scripted run, and can follow your real microphone. They are offline, one file each, with screenshots in the READMEs (ADR-100).
- Your phone for free: "find my phone" rings it, "send this file / the clipboard / a screenshot to my phone", notifications, and reminders that ring the phone, through KDE Connect on your Wi-Fi or an ntfy push away from home; Claude Code's waiting questions reach the phone too (ADR-098).
- Research on calls where Jarvis speaks: cost, Indian numbers, and the law (RESEARCH.md 2.4); not built (ADR-099).

### Fixed
- An optional argument the model writes as `{"null": true}` now counts as left out (seen with set_reminder's `at`).
- "What's on my screen", "what does this error mean": a local vision model (gemma3:4b) looks at the screen with Windows OCR's exact text; nothing leaves the laptop (ADR-096).
- "What's new in AI": a daily AI and tech digest from news feeds, saved as Markdown with links, and a line in the morning briefing (ADR-097).
- "Play lofi beats on spotify": found with Spotify's search API and started in the app, saying "Playing ..." only when Spotify does (ADR-091).
- "Start the shop project", "run redis on port 6379": compose projects and images started after a yes, then waited for until healthy or answering (ADR-092).
- "Connect to my pi": SSH profiles from config open in Windows Terminal (ADR-093).
- "What changed in my shop repo", "commit it", "push it": the local model drafts the message, and the commit and the push each ask first (ADR-094).

### Fixed
- A time given to a tool that only runs now ("open VS Code at 9" as open_app) is refused instead of running at once (ADR-095).
- "Close Spotify in 20 minutes", "open VS Code at 9": apps opened or closed later, asked once when you say it and checked by the gate again when it runs (ADR-087).
- Opening an app waits for its window and says how long it took.
- Notes: "note that ...", "what did I note yesterday", "open my notes", in a Markdown file per day in Documents (ADR-088).
- "Add groceries and 450 to my budget sheet": a row added to an Excel or CSV file after a yes, through Excel when the workbook is open (ADR-089).
- "Show 18 percent of 2400 in the calculator": the sum typed into Windows Calculator and its answer checked (ADR-090).
- Tests of their own for the router pipeline.
- Jarvis as an MCP server: `jarvis mcp serve` offers the public tools in `[mcp_server] tools` to Claude Code, Claude Desktop, and other clients, through the running Jarvis's policy gate and audit log; a call that needs a yes is asked on Jarvis's own voice and terminal, naming the client (ADR-085).
- `config/ollama/llama3.2-3b.Modelfile`: Llama 3.2 3B as a faster local model option (ADR-086).

### Changed
- The agent loop is a LangGraph graph (route, think, guard, gate, await_confirmation, execute, respond) whose policy gate no path can skip; a tool runs only with a one-time clearance from the gate for exactly its arguments (ADR-083).
- Memories and past commands are found by meaning in ChromaDB, copied once from SQLite, with SQLite as the fallback; vectors are written after the answer (ADR-084).
- "open notepad", "volume 30", and "mute" are answered without the model when the app is in the index (`[router] pipeline`). Every turn records who handled it (`handled_by`).
- The same tool call twice in one turn runs once, and a turn whose calls stay invalid stops with status `limit`.
- The web API client moved to `jarvis/adapters` and tries once more after a timeout or a 502, 503, or 504.

### Added
- Voice replies start speaking at the first sentence while the model is still writing (`[tts] stream`); `first_audio_ms` in each command's timings.
- Memories about you and about the current work, with their own room in the prompt (`[memory] user_chars`, `context_chars`).
- LangGraph and ChromaDB load in the background when `chat` or `serve` starts.

### Documentation
- ARCHITECTURE.md section 4 rewritten around the graph, with a diagram generated from the code (`scripts/architecture_graph.py`).
- Research on Open Interpreter, Leon, OpenVoiceOS, Home Assistant Assist, Willow, Pipecat, LiveKit Agents, Open WebUI, and the strongest JARVIS-style repos, with what Jarvis takes and where it does better (RESEARCH.md section 6). Piper's GPL licence confirmed, so the installer must keep it optional (ADR-006).

### Removed
- The web page, its shader, and the wake overlay, with `jarvis overlay`, the tray's Open Jarvis item, `[overlay]`, `[server] open_browser`, `glfw`, and `moderngl` (ADR-081). A new UI will be built from `ui-demos/`. Old configs and login shortcuts still work.

### Added
- The local API: `GET /health`, the bridge, and the WebSocket, refused to any browser and opened with the token in `bridge.json`.
- "What's 10 + 10" is answered at once without the model: `calculate`, a safe evaluator for sums, percentages, powers, and square roots (ADR-082).
- Past commands, answers, and finished reminders are deleted after 90 days and the audit log after 365 (`[history]`); 0 keeps them forever (ADR-075).
- Focus sessions: reminders wait, timers still ring, and the end says what you missed (ADR-078).
- Clipboard history, off by default and in memory only: "what did I copy earlier", "the second last thing I copied" (ADR-077).
- "Forget what I asked about my doctor", "delete yesterday's commands", "clear my history": `forget_history`, after a yes.

### Changed
- A locked PC says nothing private: speech is cut off, reminders wait until you unlock, and answers stay on the page (ADR-076).
- The microphone closes while the PC is locked: no wake word, push-to-talk, or dictation until you unlock it, and a question waiting for a spoken answer counts as no (ADR-074).

### Fixed
- Jarvis closed by itself on its first spoken answer when voice was off: two copies of `msvcp140.dll` in one process (R58).
- The end of a focus session was never shown in a text chat, and it was spoken over the reminder it had held. It is now printed, and Jarvis's own announcements are spoken one at a time.
- A tool call the model wrote as bare JSON was read aloud instead of run.
- A new confirmation card focused Confirm, so a stray Enter or Space could approve it. It now focuses Cancel.
- After you said no, Jarvis could say "they said no", as if the other person had refused.
- A cancelled tool showed "failed" on the page.

## [1.8.0] - 2026-11-01: New interface and wake overlay (Phase 18)

### Added
- The wake overlay: saying "Hey Jarvis" transforms the whole screen with a reactor and plasma edges, in a window that takes no clicks and no focus and stays out of screen captures. `jarvis overlay demo` shows it; `[overlay]` configures it.
- Live transcripts: your words appear as you speak, on the overlay and the page. `[voice] live_transcript`.

### Changed
- The web page is rebuilt: an icon rail, the reactor as the state indicator, the conversation as a transcript. Dark only. Every feature is kept.

## [1.7.0] - 2026-10-31: WhatsApp calls (Phase 17)

### Added
- `call_contact` calls through the WhatsApp desktop app by default, with a one-time marker proving the right chat opened; `[calls] method = "phone_link"` keeps the `tel:` way.
- `hang_up` ends a WhatsApp call.
- `install.ps1`: one command that checks for uv and Ollama (offering to install them with winget, asking first), installs the Python packages (GPU speech recognition when an NVIDIA GPU is present), downloads the models, creates `config/local.toml` and `.env` from their templates, and downloads the speech models; `-DryRun` only reports. CI runs the dry run.
- This changelog, issue and pull request templates, CODEOWNERS, and Dependabot for GitHub Actions.

### Fixed
- Desktop WhatsApp sends stopped before pressing Send, because the app's web view reports its host pane as focused.

## [1.6.0] - 2026-10-20: Screen reading (Phase 15)

### Added
- Windows OCR (`Windows.Media.Ocr`) for apps that show Windows no text: `read_window_text` falls back to it, `click` can click text found on screen (always asking first, and looking again before the click), and `read_screen` reads every screen.

## [1.5.0] - 2026-10-20: Memory by meaning and the morning briefing (Phase 14)

### Added
- Memories and past commands found by meaning with `nomic-embed-text`, vectors kept in SQLite; up to 500 memories.
- `recall`: "what did I ask about Docker last week", within today, yesterday, a week, a month, a weekday, or a date.
- `briefing`: weather, today's calendar and reminders, unread email and messages (counts and senders only); "good morning" runs it without the model, and the first command of the morning offers it.

## [1.4.0] - 2026-10-20: Faster and smaller (Phase 13)

### Added
- Semantic routing: requests with none of the keywords reach the right tools by meaning (93% of the benchmark right, 86% without).
- Whisper on the GPU with the new `gpu` extra (135 ms a command instead of 1.4 s), falling back to the CPU.
- `scripts/benchmark_stt.py`, including recording your own voice; `jarvis voice --train-wake`, which teaches "Hey Jarvis" your voice with a custom verifier.

### Changed
- Hermes 3 8B stays the default after benchmarking Llama 3.2 3B (87%) and Qwen3 4B Instruct (86%) against it (93%).

## [1.3.0] - 2026-10-20: MCP servers (Phase 12)

### Added
- An MCP client: listed tools from any MCP server become Jarvis tools behind the same policy gate (ask first unless read-only on a trusted server). GitHub's official server in Docker is configured with ten tools; `jarvis mcp list | tools | test`.

## [1.2.0] - 2026-10-20: Mail and calendar (Phase 11)

### Added
- `read_mail`, `read_email`, and `reply_email` (only after a yes, only to the people on the email) over IMAP and SMTP with an app password; `calendar_events` from a calendar's secret iCal link; `jarvis mail test` and `jarvis calendar test`.

## [1.1.0] - 2026-10-20: Dictation and media (Phase 10)

### Added
- Dictation into any app (hold Ctrl+Alt+D): spoken punctuation, typed or pasted with the clipboard restored.
- `media_control` and `now_playing` through Windows media sessions; exact phrases such as "pause the music" run without the model.

## [1.0.0] - 2026-10-20: Hardening, docs, demo (Phase 9)

### Added
- A YAML end-to-end suite run scripted in CI and against the real model, coverage in CI, a troubleshooting guide, a demo script, contributing and security guides.
- The Claude Code bridge: Claude's questions and permission prompts answered by voice or on the page, with optional phone escalation (ntfy or Twilio).
- `search_site`, `call_contact` through Phone Link, Brave as the browser when it is the default, secret redaction in what tools read.

### Fixed
- Voice that failed silently at login (logged, retried, restarted), and database damage from SQLite's WAL-reset bug (rollback journal).

## [0.8.0] - 2026-10-19: Router, memory, tray, startup (Phase 8)

### Added
- Free cloud models (Groq, then OpenRouter) for heavy public questions only, with a privacy guard that refuses private content; memory ("remember that ..."); the tray icon; starting at login.

## [0.7.0] - 2026-10-15: Notifications (Phase 7)

### Added
- Reading the Windows notification center from allowlisted apps (WhatsApp), kept a week, "anything new from Ravi".

## [0.6.0] - 2026-10-15: UI automation, browser, WhatsApp (Phase 6)

### Added
- `type_text`, `click`, `press_keys`, `read_window_text` through UI Automation; Jarvis's own browser through Playwright; contacts; `send_whatsapp`, always after a yes.

## [0.5.0] - 2026-10-15: Web UI (Phase 5)

### Added
- A local web page with chat, a live tool log, confirmation cards, and the microphone, on 127.0.0.1 with a per-launch token.

## [0.4.0] - 2026-10-15: Data APIs and system tools (Phase 4)

### Added
- Stocks, crypto, currency, and weather from free APIs with caching, rate limits, and circuit breakers; volume, brightness, lock, screenshot, clipboard, timers and reminders; `fetch_page`.

## [0.3.0] - 2026-10-15: Apps, VS Code, Docker, files (Phase 3)

### Added
- An index of installed apps, open, focus, and close by name; VS Code and Docker adapters; finding, opening, and reading files inside allowed folders.

## [0.2.0] - 2026-10-15: Voice (Phase 2)

### Added
- Push-to-talk and the "Hey Jarvis" wake word, faster-whisper, Piper or SAPI speech, spoken confirmations, barge-in.

## [0.1.0] - 2026-10-15: Skeleton (Phase 1)

### Added
- The agent loop on Hermes 3 8B through Ollama, the tool registry with risk and sensitivity labels, the policy gate, the audit log, and the CLI.

## [0.0.1] - 2026-10-14: Planning (Phase 0)

### Added
- Architecture, roadmap, setup, decisions, and risks; the repository.

[Unreleased]: https://github.com/PreeyasTumulu/JARVIS/compare/v0.3.0...main
[0.3.0]: https://github.com/PreeyasTumulu/JARVIS/releases/tag/v0.3.0
[0.2.0]: https://github.com/PreeyasTumulu/JARVIS/releases/tag/v0.2.0
[0.1.0]: https://github.com/PreeyasTumulu/JARVIS/releases/tag/v0.1.0
[0.0.1]: https://github.com/PreeyasTumulu/JARVIS/releases/tag/v0.0.1
