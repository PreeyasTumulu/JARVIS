# Architecture

This document describes how Jarvis is put together and why. It is the reference for every phase in [ROADMAP.md](ROADMAP.md). Decisions with real tradeoffs are logged in [DECISIONS.md](DECISIONS.md), and known weak spots are in [RISKS.md](RISKS.md).

## 1. Goals and non-goals

**Goals**

- One assistant core shared by voice and text. A spoken command and a typed command take the same path and produce the same result.
- Local by default. The planner is Nous Hermes 3 (8B, quantized) on Ollama, called through an OpenAI-compatible client.
- Typed, auditable tools. Each tool is a Python function with a generated JSON schema, a risk level, and a sensitivity label.
- Safety enforced in code. Risk levels, allowlists, confirmation, cancellation, and the privacy router work even if the model misbehaves.
- Models are swappable by config only, and the agent loop can move to LangGraph later without rewriting tools.

**Non-goals (for now)**

- Multi-user or remote access. The web UI binds to `127.0.0.1` only.
- Running as administrator. Jarvis runs as a normal user and cannot drive elevated windows. This is intentional.
- Vision-first computer use. A vision fallback exists behind a feature flag, but structured automation is the main path.
- A general-purpose shell tool. Jarvis uses specific adapters (VS Code, Docker, etc.) instead. See ADR-010.

## 2. System overview

```mermaid
flowchart LR
  subgraph Inputs
    MIC[Microphone] --> WW[Wake word<br/>openWakeWord]
    MIC --> PTT[Push-to-talk<br/>hotkey]
    WW --> STT[STT<br/>faster-whisper]
    PTT --> STT
    CLI[Text CLI]
    WEB[Web UI<br/>FastAPI + WebSocket]
  end

  STT --> SES[Session]
  CLI --> SES
  WEB --> SES
  SES --> AG[Agent core<br/>tool-calling loop]
  AG <--> RT[Model router]
  RT --> LOC[Ollama<br/>Hermes 3 8B]
  RT -. public context only .-> CLD[Cloud model<br/>e.g. DeepSeek]
  AG --> POL[Policy gate<br/>risk, allowlists, confirm]
  POL --> REG[Tool registry]
  REG --> TA[Apps and UI automation]
  REG --> TF[Files]
  REG --> TW[Web and browser]
  REG --> TD[Data APIs]
  REG --> TM[Messaging]
  REG --> TN[Notifications]
  REG --> TS[System]
  AG --> BUS[Event bus]
  BUS --> WEB
  BUS --> CLI
  BUS --> TTS[TTS<br/>Piper / Kokoro / SAPI]
  BUS --> DB[(SQLite<br/>audit, history,<br/>prefs, contacts)]
```

| Component | Responsibility | Main libraries |
|---|---|---|
| Inputs | Turn speech or text into a `UserInput` for a session | sounddevice, openWakeWord, faster-whisper |
| Session | Holds conversation state for one user, shared by every input channel | stdlib asyncio |
| Agent core | Plan with the LLM, call tools, loop until done or limits hit | openai (AsyncOpenAI), pydantic |
| Model router | Pick local or cloud model per turn, enforce the privacy guard | openai, httpx |
| Policy gate | Decide safe / confirm / blocked for each call, run confirmations | pydantic |
| Tool registry | Register typed tools, generate JSON schemas, execute with timeouts | pydantic, stdlib inspect |
| Tools | Do the actual work on Windows and the web | UI Automation (comtypes), SendInput, Playwright (Edge), httpx, pywinrt |
| Event bus | Fan out typed events to UI, CLI, TTS, and the audit log | stdlib asyncio |
| Storage | Preferences, contacts, history, audit log, caches | sqlite3 (WAL mode) |

## 3. Lifecycle of one command

Example: "Message Mom that I'll be late."

```mermaid
sequenceDiagram
    actor U as You
    participant I as Voice / UI / CLI
    participant A as Agent core
    participant M as Hermes 3 (local)
    participant P as Policy gate
    participant T as send_whatsapp
    participant L as Audit log

    U->>I: "Message Mom that I'll be late"
    I->>A: UserInput(text, source=voice)
    A->>M: messages + tool schemas
    M-->>A: tool_call send_whatsapp(contact="Mom", message="I'll be late")
    A->>T: prepare(args) resolves "Mom" to one contact, no side effects
    A->>P: evaluate(prepared call)
    P-->>I: ConfirmationRequest "Send 'I'll be late' to Amma (+91 98xxx)? Yes or no."
    U->>I: "Yes"
    I->>P: approve(request_id)
    P->>T: execute(prepared call)
    T-->>A: ToolResult(ok, speech="Sent to Amma.")
    A->>L: tool, args, decision=confirmed, via=voice, result
    A->>M: tool result
    M-->>A: final answer
    A-->>I: "Done, I sent it to Amma."
```

If "Mom" matched two contacts, `prepare` would return a clarification request and the agent would call `ask_user` before anything is confirmed or sent.

## 4. Agent core

### 4.1 State

`AgentState` is a typed, serializable model (pydantic) so the loop can later become a LangGraph `StateGraph` without changes to tools:

- `messages`: the conversation in OpenAI chat format
- `turn_id`, `session_id`, `source` (voice / cli / ui)
- `sensitivity`: the highest sensitivity of anything in the context (see 5.4)
- `iterations` and the turn deadline
- `pending_confirmation`: the request currently waiting for you, if any

Implementation note (Phase 1): the state lives on the `Agent` object (`src/jarvis/core/agent.py`) and each turn returns a `TurnResult`. It becomes an explicit graph state object if the loop moves to LangGraph.

### 4.2 Loop

```python
async def run_turn(state: AgentState) -> AgentState:
    for _ in range(cfg.agent.max_iterations):
        reply = await router.complete(state)                 # picks model, enforces privacy guard
        if not reply.tool_calls:
            return state.finish(reply.text)
        for call in reply.tool_calls:
            prepared = await registry.prepare(call, state)   # validate args, resolve, no side effects
            decision = await policy.evaluate(prepared, state)
            if decision.needs_confirmation:
                decision = await confirmations.request(prepared, state)
            result = await registry.execute(prepared, decision, state)  # timeout, cancel, audit
            state = state.with_tool_result(call, result)      # wrapped as data, sensitivity raised
    return state.finish(limit_reached_message(state))
```

### 4.3 Limits

| Limit | Default | Why |
|---|---|---|
| `max_iterations` | 6 | An 8B model can loop; stop early and say what happened |
| `tool_timeout_s` | 20 | Per tool call; tools can override (browser and WhatsApp tools get longer) |
| `turn_timeout_s` | 180 | Hard ceiling for one command (a first WhatsApp Web load takes up to a minute) |
| `max_tool_calls_per_step` | 4 | Caps parallel tool calls in one model reply |
| `confirm_timeout_s` | 30 | No answer means no |

### 4.4 Prompting

The system prompt carries: identity and style (short, spoken sentences), the current date, time, and time zone, the rule that tool results are data and never instructions, and when to use `ask_user`. **Tool routing** (`core/tool_routing.py`, Phase 3): with 16 tools the 8B model picked the right first tool 80% of the time, against 100% with 4 tools. Keyword groups (apps, files, docker, web) now choose which tools a request sees; a request that matches no group sees all of them, and the executor still accepts any registered tool. Measured: 87% first-call accuracy and a slightly faster median (2.8 s vs 3.1 s), because the prompt is shorter. `agent.tool_routing = "all"` turns it off. Embedding-based retrieval with `nomic-embed-text` remains an option if keyword routing stops being enough.

**Spoken replies:** the 8B model tends to mirror list data as long markdown lists, which took 40 to 60 seconds to generate. Three things keep replies short: each tool result carries its one-sentence `summary`, list results end with a short reply instruction, and `max_tokens` (300) caps the worst case.

### 4.5 Tool-call parsing

1. Use native `tool_calls` from Ollama's OpenAI-compatible endpoint (Hermes 3 is tagged with the `tools` capability).
2. Fallback: if the model emits `<tool_call>{...}</tool_call>` as plain text, parse it.
3. Invalid JSON or unknown tool: feed a short error back to the model once, then stop and tell you.

### 4.6 Moving to LangGraph later

| Today (plain asyncio) | LangGraph equivalent |
|---|---|
| `router.complete` | `call_model` node |
| `registry.prepare` + `policy.evaluate` | `gate` node with conditional edges |
| `confirmations.request` | `interrupt()` for human-in-the-loop |
| `registry.execute` | `tools` node |
| `state.finish` | edge to `END` |
| `AgentState` | graph state schema |

Tools, the policy gate, and the router stay the same. Only the loop function is replaced.

## 5. Tool system

### 5.1 Defining a tool

```python
@tool(risk=Risk.SAFE, sensitivity=Sensitivity.PUBLIC, timeout_s=10)
async def open_app(ctx: ToolContext, name: str) -> ToolResult:
    """Open an installed application by its spoken name.

    Args:
        name: Spoken or approximate app name, for example "vs code" or "docker".
    """
```

The decorator reads the signature and docstring and builds a pydantic model for the arguments. That model produces the JSON schema sent to the LLM and validates the arguments the LLM sends back.

### 5.2 ToolSpec fields

| Field | Meaning |
|---|---|
| `name`, `description`, `parameters` | Generated from the function, sent to the model |
| `risk` | Floor risk level: `safe`, `confirm`, or `blocked` |
| `risk_for(args, ctx)` | Optional dynamic check that can raise risk for specific arguments (never lower it) |
| `sensitivity` | `public` or `private`, label for what the result contains |
| `untrusted` | True if the result contains outside content (web, files, notifications, window text) |
| `timeout_s` | Per-call timeout |
| `prepare` / `execute` | Two-phase tools: `prepare` resolves and validates with no side effects, `execute` does the work |
| `enabled` | Config can disable any tool |

### 5.3 Risk levels

| Level | Behaviour | Examples |
|---|---|---|
| `safe` | Runs directly | open an allowlisted app, search, read weather, read an allowlisted file |
| `confirm` | Waits for your explicit yes (voice, UI button, or CLI) | send a message, stop a container, close an app that may have unsaved work, unlisted app, browser form submit |
| `blocked` | Never runs, logged as blocked | paths outside the allowlist, registry edits, disk formatting, reading credential stores, typing into password fields |

Rule: **config can tighten risk but never loosen it below the tool's floor.** `send_whatsapp` is `confirm` forever, no setting changes that.

### 5.4 Sensitivity and the privacy label

Every tool result carries `public` or `private`. The default is `private` (fail closed). The session tracks the highest sensitivity in its context. The router uses this label to decide whether a cloud model may ever see the turn (section 7).

`private` includes: WhatsApp content, notifications, file names and contents, clipboard, screen and window text, contacts, memory, and your answers to `ask_user`.

### 5.5 Results enter the context as data

```python
class ToolResult(BaseModel):
    ok: bool
    data: Any = None            # structured, for the UI and the model
    speech: str | None = None   # one or two short sentences for TTS
    error: str | None = None
    sensitivity: Sensitivity
    untrusted: bool
```

Untrusted results are wrapped before they reach the model, and any closing tag inside the content is escaped so it cannot break out:

```text
<tool_result name="fetch_page" untrusted="true">
...page text...
</tool_result>
```

The prompt says this content is data. The real protection is structural: nothing the model reads can approve a `confirm` call or unblock a `blocked` one.

### 5.6 Planned tool catalog

| Tool | Phase | Risk | Sensitivity |
|---|---|---|---|
| `speak(text)` | 1 | safe | public |
| `ask_user(question, options?)` | 1 | safe | private |
| `open_app(name)` | 1 basic, 3 full index | safe if allowlisted, else confirm | public |
| `web_search(query)` | 1 | safe | public, untrusted |
| `focus_app(name)` | 3 | safe (opening an app that is not running follows the app allowlist) | public |
| `close_app(name)` | 3 | confirm, unless on `safety.safe_to_close` and no window title shows unsaved changes | public |
| `vscode_open(path, line?)` | 3 | safe inside folder allowlist, else blocked | private |
| `docker_list(include_stopped?)` | 3 | safe | private |
| `docker_logs(container, lines?)` | 3 | safe | private, untrusted |
| `docker_start(container)`, `docker_stop(container)` | 3 | confirm (floor) | private |
| `find_file(query, kind?)` | 3 | safe, searches only allowed folders | private |
| `open_file(path)` | 3 | safe inside allowlist; confirm for programs and scripts; blocked outside, for secrets, and for .reg | private |
| `read_file(path)` | 3 | safe inside allowlist; blocked outside and for secret-looking files | private, untrusted |
| `get_selected_file()` | 3 | safe | private |
| `open_url(url)` | 3 | safe for http and https, blocked for any other scheme; confirm under the egress rule (6.1, step 4a) | public |
| `market_data(query)` | 4 | safe | public |
| `weather(place?, day?)` | 4 | safe | public |
| `convert_currency(amount, from_currency, to_currency)` | 4 | safe | public |
| `crypto_price(coin, currency?)` | 4 | safe | public |
| `fetch_page(url)` | 4 | safe; blocked for local addresses; confirm when private data and outside content are in context (egress) | public, untrusted |
| `set_volume(level?, change?, mute?)`, `set_brightness(level?, change?)`, `lock_screen()` | 4 | safe | public |
| `screenshot()` | 4 | safe | private |
| `clipboard_read()` / `clipboard_write(text)` | 4 | safe | private, untrusted / public |
| `set_timer`, `set_reminder`, `list_reminders`, `cancel_reminder(which)` | 4 | safe; cancelling more than one confirms | private |
| `type_text(app, text, field?)`, `click(app, target)`, `press_keys(app, keys)` | 6 | confirm, or safe inside trusted apps except destructive targets and closing keys; always confirm in messaging apps and terminals; blocked in Registry Editor, consoles, sign-in prompts, password managers, and password fields | public |
| `read_window_text(app)` | 6 | safe (blocked for the apps above) | private, untrusted |
| `browser_open(url, search?)`, `browser_read()`, `browser_click(target)`, `browser_type(text, target?, submit?)` | 6 | safe; submits, purchases, and deletes confirm (search boxes do not); passwords, card numbers, one-time codes, local addresses, and WhatsApp sites blocked; open and type are `egress` | private, untrusted |
| `send_whatsapp(contact, message)` | 6 | confirm (floor, cannot be lowered); asks which contact when a name fits several | private |
| `read_notifications(person?)` | 7 | safe; only apps on `notifications.apps` | private, untrusted |
| `remember(fact)`, `forget(fact)` | 8 | safe | private |

## 6. Safety model

### 6.1 Policy gate, in order

1. The tool exists and is enabled. Otherwise the model gets "unknown tool".
2. Arguments validate against the schema. Otherwise the model gets the validation error.
3. Static risk `blocked`: deny.
4. Dynamic `risk_for(args)`: for example a path outside the folder allowlist becomes `blocked`, an app outside the app allowlist becomes `confirm` (or `blocked`, by config).
4a. Context rule: a tool marked `egress` (it sends a request to an address the model picks) becomes at least `confirm` when the model's context holds both private tool output and untrusted outside content (ADR-029). The agent computes these flags from the messages it will send, so trimmed history drops out.
5. Global blocked patterns: registry tools, disk tools, credential stores, password fields.
6. `confirm`: run the confirmation protocol.
7. `safe`: run.

Every outcome, including blocked and denied attempts, is written to the audit log.

### 6.2 Confirmation protocol

- The confirmation is about the **prepared** call: resolved contact, resolved path, exact message text. The request stores a hash of the prepared arguments, and `execute` refuses to run if anything changed after approval.
- Any channel can answer: a UI button, a CLI prompt, or voice.
- Voice approval needs a clear affirmative from a short list ("yes", "yes send it", "confirm", "go ahead"). Anything else, silence, or a timeout counts as no.
- One pending confirmation per session. A new command while one is pending cancels it.
- Content read from tools can never answer a confirmation. Only the input channels can.

### 6.3 Allowlists

- **Apps:** `safety.app_allowlist` in config. Unlisted apps follow `safety.unlisted_apps` (`confirm` by default, or `block`).
- **Folders:** `files.allowed_folders` (default Documents, Desktop, Downloads, resolved through Windows known folders so OneDrive redirection works). Paths are resolved (`Path.resolve()`, junctions and symlinks followed) before the check, so `..` and links cannot escape. Secret-looking names (`.env`, `*.pem`, `id_rsa*`, `*password*`, ...) are blocked even inside, opening programs and scripts asks first, and `.reg` files are blocked (`tools/files/guard.py`).
- **Invented paths:** if the model passes a path that does not exist, the file tools search for the words in it and use the best match only when it clearly stands out; otherwise the model gets the closest real paths and must pick one or ask.
- **UI automation:** `safety.trusted_ui_apps` lists apps where generic `click` / `type_text` / `press_keys` run without confirmation, except targets that look destructive (send, delete, remove, buy, pay, submit, close, don't save, ...) and closing shortcuts (Alt+F4, Ctrl+W). Messaging apps and terminals are never trusted, whatever the config says, and a few apps are blocked outright (ADR-042, `tools/ui/guard.py`).

### 6.4 Cancellation

- Each turn runs as one asyncio task, and stopping a turn is task cancellation. `Agent.cancel()` is safe to call from any thread. Triggers: Ctrl+C in the CLI (Phase 1), the global stop hotkey and the voice command "stop" (Phase 2), and the Stop button in the UI (Phase 5).
- "Stop" is matched deterministically on the transcript before the LLM sees it, so it works even when the model is slow.
- On cancel: the in-flight LLM request is aborted, the running tool is cancelled, TTS stops, and any pending confirmation is denied. The audit log records the call as `cancelled`, and the conversation is rolled back to a clean state so the next command works normally.
- Work running in a thread (for example UI automation) cannot be killed safely in Python. Those tools check a stop flag between steps, so a stuck call may take a moment to wind down. This is called out in RISKS.md.

### 6.5 Audit log

Each tool call records: timestamp, session and turn ids, tool, full arguments, risk, decision (`auto`, `confirmed`, `denied`, `blocked`, `timeout`, `cancelled`), the confirming channel, success, a truncated result, error, and duration. The audit log is local only. `audit.redact_private = true` stores a hash and length instead of private argument text if you ever want that.

## 7. Model layer and router

### 7.1 One client for every model

All models are reached through `AsyncOpenAI(base_url=..., api_key=...)`. Providers live in config:

```toml
[llm.providers.local]
base_url = "http://localhost:11434/v1"
model = "jarvis-hermes3"          # hermes3:8b plus config/ollama/hermes3-8b.Modelfile (num_ctx)
api_key_env = ""                  # Ollama ignores the key

[llm.providers.deepseek]
base_url = "https://api.deepseek.com/v1"
model = "deepseek-chat"
api_key_env = "DEEPSEEK_API_KEY"
```

Ollama's OpenAI-compatible endpoint does not accept a context length per request, so Jarvis ships a Modelfile (`num_ctx`, low temperature) and creates a local alias model from it. See SETUP.md.

### 7.2 Routing rules

| Situation | Model |
|---|---|
| Default | local |
| Cloud disabled (`router.cloud_enabled = false`, the default until Phase 8) | local, always |
| Turn is heavy reasoning (explicit "think harder" or a heuristic) **and** context is all `public` | cloud allowed |
| Context contains anything `private` | local, always |
| Cloud provider down, slow, or over budget | local |

### 7.3 The privacy guard

The guard is code, not a prompt:

- A cloud turn gets a **fresh context**: system prompt, the current request, and `public` tool results only. Earlier private history is never forwarded.
- A cloud turn sees only `public` tools (web search, fetch page, market data). If it needs a private tool, the turn falls back to local.
- The cloud client wrapper refuses any request whose state sensitivity is `private` and raises, so a router bug fails loudly instead of leaking.
- Tests use a fake cloud client that fails the test if any private marker reaches it.

## 8. Voice pipeline

```mermaid
stateDiagram-v2
    [*] --> Idle
    Idle --> Listening: wake word or push-to-talk down
    Listening --> Transcribing: end of speech (VAD) or push-to-talk up
    Transcribing --> Idle: "stop" or empty transcript
    Transcribing --> Thinking: transcript
    Thinking --> Speaking: reply or confirmation question
    Speaking --> Listening: push-to-talk (barge-in)
    Speaking --> Idle: done
    Thinking --> Idle: stop hotkey
```

- **Capture:** sounddevice at 16 kHz mono in 80 ms frames, callback thread feeding an asyncio queue (`voice/audio.py`). Device names resolve to the MME entry, which accepts 16 kHz directly.
- **One reader:** `VoiceSession._frame_loop` (`voice/session.py`) routes every frame to the push-to-talk buffer, the endpointer, or the wake word detector, depending on what the session is doing.
- **Push-to-talk:** hold a hotkey, speak after the beep, release. The microphone is open only while the key is held. Hotkeys use Win32 `RegisterHotKey` on their own thread; releases are detected by polling the key (`platform/hotkeys.py`).
- **Wake word (opt-in, `--wake`):** openWakeWord "hey jarvis" with the ONNX backend (TFLite is not supported on Windows). The microphone stays open in this mode.
- **Endpointing:** Silero VAD probabilities per frame feed `Endpointer` (`voice/endpoint.py`), which ends the recording after 0.8 s of silence, after 12 s, or if nothing was said within 5 s.
- **STT:** faster-whisper `small.en`, CPU `int8`, 8 threads, with a short vocabulary hint (app names). Silent or tiny clips are skipped, and Whisper's typical silence hallucinations ("Thank you.") are dropped.
- **TTS:** Piper (optional extra, GPL-3.0) speaks sentence by sentence, synthesizing the next sentence while the current one plays; stop cuts it within about 50 ms. Windows SAPI is the fallback. Kokoro arrives with packaging in Phase 8.
- **Deterministic phrases** (`voice/phrases.py`): "stop" style commands and yes/no answers never go through the model.
- **Confirmations by voice:** `VoiceChannel` speaks "Should I open Paint? Say yes or no." and waits for the next utterance. In voice mode the agent's channel is `FirstAnswerChannel(voice, keyboard)`, so typing y or n also works (ADR-022).
- **Self-trigger:** without echo cancellation, speaker output can trigger the wake word. Wake word detection is paused while Jarvis speaks and for 0.4 s after. Barge-in uses the push-to-talk hotkey.
- **Timings:** every voice command stores `audio_ms`, `stt_ms`, `pre_turn_ms`, `llm_ms`, `first_tool_ms`, and `turn_ms` in `command_history.timings_json`; the session prints the median "end of speech to first action" when it exits.

## 9. Interfaces

### 9.1 CLI

`jarvis chat` is a rich terminal client on the same session API: it shows tool calls live, prompts y/n for confirmations, and Ctrl+C cancels the current turn (a second Ctrl+C quits).

### 9.2 Web UI

FastAPI serves a static page (plain HTML, CSS, and JavaScript, no build step) and one WebSocket (`src/jarvis/server/`). `jarvis serve` runs it on the same event loop as the agent, voice, and reminders, so all of them share one conversation (ADR-035, ADR-036).

| Direction | Message | Purpose |
|---|---|---|
| client to server | `command {text}` | Typed command (refused while another runs) |
| client to server | `confirm {request_id, approved}` | Confirm or Cancel; only `true` approves |
| client to server | `answer {question_id, text}` | Answer to `ask_user` |
| client to server | `stop {}` | Stop button and Esc |
| client to server | `mic {on}` | Talk button, same as holding the push-to-talk hotkey |
| client to server | `audit {}` | Last 50 audit rows |
| client to server | `contacts {}`, `contact_add {name, phone, aliases}`, `contact_remove {id}`, `contact_import {text}` | Contacts tab (the model has no tool that changes contacts) |
| server to client | `hello {version, model, busy, voice, history, open}` | On connect: recent turns, open cards and questions |
| server to client | every bus event, e.g. `turn_started`, `tool_call_started`, `tool_call_finished`, `confirmation_requested`, `confirmation_resolved`, `assistant_message`, `turn_finished`, `voice_state_changed`, `transcript_heard`, `reminder_due` | The event's own fields |
| server to client | `question {question_id, question, options}`, `question_closed` | `ask_user` cards |
| server to client | `audit {rows}`, `error {message}` | Audit view, errors |
| server to client | `contacts {contacts, note, error, added}` | Contacts tab, after every change (to every tab) |

**Local UI security.** Browsers do not apply CORS to WebSockets, so any website you visit could try to connect to `ws://127.0.0.1`. The server therefore binds to `127.0.0.1` only, checks the `Origin` header, and requires a random token generated at each launch (opened for you in the URL). It also rejects a foreign `Host` header (DNS rebinding) and sends a Content-Security-Policy that forbids other sites from framing the page, so nobody can overlay an invisible Confirm button. Everything the page shows is inserted as text, never as HTML, because replies can contain text from web pages.

### 9.3 Tray (Phase 8)

pystray icon with status, mic toggle, open UI, and quit.

## 10. Storage

SQLite in WAL mode at `%LOCALAPPDATA%\Jarvis\jarvis.db`, migrations tracked with `PRAGMA user_version`.

| Table | Contents |
|---|---|
| `preferences` | key, JSON value, updated_at |
| `contacts` | name (unique, compared case-insensitively), phone (E.164), notes, created_at |
| `contact_aliases` | alias to contact (many to many, so "Ravi" can name two people on purpose) |
| `command_history` | input text, source, final reply, status, model, latency |
| `audit_log` | see 6.5 |
| `api_cache` | cache key, JSON value, fetched_at, expires_at (quotes, rates, weather, places, symbols) |
| `app_index` | display name, normalized name, kind (shortcut or packaged app), launch target or AppID, executable name |
| `file_index` | path, name, normalized name, folder flag, size, modified time (only used when Everything is not installed) |
| `index_meta` | when each index was last built and how many items it has |
| `notifications` | Windows id, app id, app name, title, body, created_at, seen_at, read_at (allowed apps only; deleted after `keep_days`) |
| `reminders` | kind (timer or reminder), message, due_at, created_at, status (pending, done, cancelled, missed), fired_at |
| `memories` | Phase 8 facts, optional embedding |

Everything that is personal (database, logs, the two browser profiles `browser-profile` and `whatsapp-profile`, downloaded voice models) lives under `%LOCALAPPDATA%\Jarvis\`, outside the repo, so it can never be committed by accident.

At every start Jarvis runs SQLite's quick check. A damaged database is renamed to `jarvis.db.corrupt-<time>` untouched, and the readable rows of preferences, history, audit, reminders, and contacts are copied into a fresh one (ADR-043).

## 11. Concurrency on Windows

| Work | Where it runs |
|---|---|
| Agent loop, HTTP, WebSocket, Playwright | Main asyncio loop (Proactor loop, the Windows default) |
| Audio capture | sounddevice callback thread, handed to asyncio with `call_soon_threadsafe` |
| STT and TTS inference | Thread pool via `asyncio.to_thread` (ctranslate2 and onnxruntime release the GIL) |
| COM (UI Automation, audio, Explorer selection) | One dedicated worker thread with COM initialized (`platform/com.py`); UI tools submit jobs to it |
| Synthetic keys (`SendInput`) | Thread pool, in bursts of 24 characters with a foreground check before each, so a stop or a focus change ends typing between bursts |
| Global hotkeys | Dedicated thread with a Win32 message loop (`RegisterHotKey`), handing events to asyncio with `call_soon_threadsafe` |
| Wake word, VAD | Thread pool via `asyncio.to_thread`, one frame at a time (a few milliseconds each) |
| Notification watcher | Main asyncio loop: pywinrt awaitables, one poll every `notifications.poll_s` seconds |
| Tray icon | pystray's own thread |

## 12. Configuration

- `config/jarvis.toml`: committed defaults.
- `config/local.toml`: your overrides (allowlists, home city, hotkeys). Gitignored.
- `.env`: secrets only (API keys). Gitignored; `.env.example` is committed.
- Loaded with `tomllib` and python-dotenv into typed pydantic models (`src/jarvis/config.py`). Unknown keys are rejected, so a typo fails at startup with a clear message instead of being silently ignored.

```toml
[agent]
max_iterations = 6
turn_timeout_s = 180

[safety]
app_allowlist = ["Visual Studio Code", "Docker Desktop", "Claude", "WhatsApp", "Google Chrome", "Notepad"]
unlisted_apps = "confirm"
safe_to_close = ["Calculator", "Settings", "File Explorer"]
trusted_ui_apps = ["Notepad"]       # Phase 6

[browser]
channel = "msedge"                  # or "chromium" (Playwright's build)

[contacts]
default_country_code = "91"         # for numbers saved without one

[whatsapp]
method = "auto"                     # Web once linked, else the desktop app

[notifications]
apps = ["WhatsApp", "Claude"]       # nothing else is read or stored
keep_days = 7

[files]
allowed_folders = ["{documents}", "{desktop}", "{downloads}"]

[voice]
stt_model = "small.en"
stt_device = "cpu"
tts_engine = "piper"            # piper | kokoro | sapi
wake_word = "hey_jarvis"

[ui]
host = "127.0.0.1"
port = 8765
```

## 13. Repository layout

```text
jarvis/
  pyproject.toml              uv project, ruff, mypy, pytest config
  .env.example
  .github/workflows/ci.yml    lint, format, mypy, tests, dash check on windows-latest
  config/
    jarvis.toml               committed defaults
    local.example.toml        template for your gitignored local.toml
    ollama/*.Modelfile        local model aliases with num_ctx (8B and 3B)
  docs/                       this documentation, plus benchmarks/
  scripts/                    benchmark_tools.py, check_dashes.py
  src/jarvis/
    __main__.py               python -m jarvis
    cli.py                    jarvis chat, ask, voice, serve, setup-voice, index, contacts, whatsapp,
                              notifications, audit, version
    console.py                terminal channel: live tool log, y/n confirmations, questions
    app.py                    wires settings, storage, model, tools, and agent together
    services.py               shared helpers tools use (TTS, app index, search backend)
    config.py
    core/                     agent loop, executor (gate + confirm + audit), tool routing, events,
                              channel, prompts
    llm/                      OpenAI-compatible client, tool-call text parser (router in Phase 8)
    tools/
      registry.py             @tool decorator, schema generation
      policy.py               risk evaluation, allowlists
      catalog.py              the list of tools exposed to the model
      interaction.py          speak, ask_user
      apps/                   app index (SQLite), open/focus/close, window matching, vscode, docker
      ui/                     type_text, click, press_keys, read_window_text; key parsing; risk rules
      files/                  guard (allowlist, secrets), index and search (Everything or SQLite),
                              readers (text, PDF, docx), "this file" from Explorer or VS Code
      web/                    search, open_url, fetch_page
      browser/                Jarvis's browser (Playwright, two profiles), page snapshot script,
                              browser_open, browser_read, browser_click, browser_type
      data/                   http (cache, token buckets, breakers), market chain, weather, currency,
                              crypto, spoken number formatting
      messaging/              contact book and vCard import, send_whatsapp, WhatsApp Web and desktop,
                              WhatsApp Web selectors
      notifications/          store and allowlist, watcher (polling), read_notifications
      system/                 volume, brightness, lock, screenshot, clipboard, timers and reminders
    voice/
      audio.py                microphone stream, player, earcons, device resolution, mic check
      session.py              the voice loop (states, frame routing, turns, confirmations)
      channel.py              VoiceChannel: spoken confirmations and questions
      stt.py, wake.py         faster-whisper; openWakeWord and Silero VAD
      endpoint.py, phrases.py end-of-speech logic; stop words, yes/no, transcript cleanup
      models.py, runner.py    model downloads; `jarvis voice` and `jarvis setup-voice`
      tts/                    TTS interface, Piper, SAPI, engine factory
    storage/                  sqlite connection, migrations, repositories
    server/                   app.py (routes, security), hub.py (tabs, WebChannel), runtime.py
                              (requests from tabs), serve.py (uvicorn, voice, reminders), static/
    platform/                 Windows helpers: hotkeys, known folders (OneDrive), window list/focus/close,
                              COM thread, volume, display (brightness, lock, screenshot), clipboard,
                              UI Automation (uia.py), synthetic keys and clicks (sendinput.py),
                              the notification center (notifications.py)
  tests/
    unit/                     tools with mocks, policy, router, registry
    integration/              sqlite, real Ollama (marked, optional)
    e2e/                      scripted command suite (YAML scenarios)
```

## 14. Observability

- stdlib `logging` with a rotating file in `%LOCALAPPDATA%\Jarvis\logs` and a rich console handler.
- The audit log is the source of truth for what Jarvis did. `jarvis audit --last 20` prints it.
- Each turn records latency per stage (STT, LLM, tools, TTS) in `command_history` so slow spots are measurable.

## 15. Testing approach

- **Unit:** every tool with its Windows or network dependency mocked (httpx's MockTransport for HTTP, where anything unrouted fails like a dead network; fakes for yfinance, system controls, UI Automation, keyboard input, the browser, and WhatsApp). Real-browser tests (`pytest -m browser`) run the page snapshot script and the WhatsApp Web send flow against local pages in Edge. Policy, router, and registry have their own tests, including "private data never reaches the cloud client".
- **Scripted e2e:** YAML scenarios of utterance to expected tool calls. They run against a scripted fake LLM in CI, and optionally against real Ollama locally (`pytest -m llm`) to measure tool-choice accuracy.
- **CI:** GitHub Actions on `windows-latest`: ruff, mypy, unit tests, and a check that no em or en dashes appear in docs or comments.
