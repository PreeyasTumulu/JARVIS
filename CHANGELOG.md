# Changelog

Every phase of Jarvis, newest first. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow [Semantic Versioning](https://semver.org/).

Versions 0.4.0 to 1.8.0 are merged to `main` with green CI, but not tagged: they wait for a hands-on test. Details, test commands, and measurements for each are in [docs/ROADMAP.md](docs/ROADMAP.md); every design decision is in [docs/DECISIONS.md](docs/DECISIONS.md).

## [Unreleased]

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
