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

## Open decisions

These are asked when the phase starts, not before.

| Phase | Decision | Options |
|---|---|---|
| 6 | WhatsApp automation | Accept the account risk described in RISKS.md |
| 7 | Notification source | Windows listener vs WhatsApp Web polling, after the spike |
| 8 | Cloud provider and budget | DeepSeek or another OpenAI-compatible API, monthly cap |
| 8 | Packaging | uv-based launcher vs PyInstaller build |
