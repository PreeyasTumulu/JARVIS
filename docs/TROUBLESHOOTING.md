# Troubleshooting

Start with the log: `%LOCALAPPDATA%\Jarvis\logs\jarvis.log`. A Jarvis started at login has no console, so everything it would have printed is there. `uv run jarvis audit --last 20` shows what it actually did. Known weak spots and their background are in [RISKS.md](RISKS.md).

## "Hey Jarvis" does not wake it

1. **Is voice running?** The tray tooltip says "Ready" when it is, and "Voice is not ready yet, retrying" while Jarvis keeps trying. In the log, look for `Whisper small.en loaded` and `Voice could not start: ...`; the reason is written there (RISKS.md R33).
2. **Is it hearing you?** Close any Jarvis that is running, then:

   ```powershell
   uv run jarvis voice --wake-test 30
   ```

   Say "Hey Jarvis" a few times from where you usually sit. Each half second prints the microphone level and the wake word score; `WAKE` marks a detection.
   - Level stays around 0 to 10 even while you talk: the wrong microphone. `uv run jarvis voice --list-devices`, then set `input_device` under `[voice]` in `config/local.toml` (on this laptop, `"Microphone Array"`).
   - Level moves and the score rises after each "Hey Jarvis" but stays under the threshold (this laptop's first real test: 0.25 to 0.45 against 0.5): teach it your voice, about two minutes:

     ```powershell
     uv run jarvis voice --train-wake
     ```

     Then run the wake test again and restart Jarvis (tray, Quit, then start it). A quick stopgap is a lower `wake_threshold` under `[voice]`; the wake test suggests one, but it also makes false wakes more likely (ADR-064).
   - It fires on its own: raise `wake_threshold`.
3. **After sleep or plugging in a headset** the stream can go quiet; Jarvis reopens it after 3 seconds of silence from the device and logs `The microphone sent no audio for 3s; reopening it` (R34).
4. **Windows privacy:** Settings, Privacy and security, Microphone: "Let desktop apps access your microphone" must be on.

## Jarvis does not start at login

`uv run jarvis startup` shows the shortcut. If the log shows nothing from the last login, start the shortcut by hand (`Win+R`, `shell:startup`, open `Jarvis.lnk`) and watch the log. A startup that never reaches the page writes every thread's stack to `logs\startup-hang.txt` after five minutes. Another Jarvis on the same port makes the second one exit (`Port 8765 is in use`).

## The model

| Symptom | Check |
|---|---|
| "Connection refused" to the model | Is Ollama running? Open `http://localhost:11434`. |
| Slow replies | `ollama ps` shows the CPU and GPU split. Close GPU-heavy apps; the Ollama speed settings (DECISIONS.md, open decision 3) help; try a 4B model (RESEARCH.md section 3). |
| It answers in text instead of calling a tool | Use the `jarvis-hermes3` model (SETUP.md 3) and an up-to-date Ollama. |
| Long, rambling spoken replies | Should be rare since Phase 9 (results with a summary or long lists ask for one or two sentences). Report the command. |
| Every question stays local | `GROQ_API_KEY` or `OPENROUTER_API_KEY` missing from `.env`, a daily cap reached, or the question touches something private. `[router] escalate` decides the rest. |

## Voice

| Symptom | Check |
|---|---|
| "is sending pure silence" | The selected microphone is muted or virtual (AudioRelay, Voicemeeter, DroidCam). Pick a real one with `input_device`. |
| "Could not register" a hotkey | Another app owns that combination. Change `ptt_hotkey` or `stop_hotkey` under `[voice]`. |
| Speech recognition is slow (over a second) | The log says where Whisper loaded ("loaded on the GPU"). For the GPU: `uv sync --extra voice --extra piper --extra gpu`. A game holding the GPU memory pushes it back to the CPU. |
| It mishears names | Say numbers when answering a list ("two"); add app names to the vocabulary hint by using them; `stt_model = "small.en"` is the default, `medium.en` is slower but better. |

## Apps, files, the browser, WhatsApp

| Symptom | Check |
|---|---|
| "Jarvis's browser did not start" | `[browser] channel` follows your default browser (Brave, Chrome, or Edge). Set `channel = "brave"` or `executable = "C:/path/to/browser.exe"` in `config/local.toml`. With `channel = "chromium"`, run `uv run playwright install chromium` (RISKS.md R23). |
| A site search opens the wrong site | `search_site` matches names loosely; add your own under `[search] sites` in `config/local.toml`. |
| Typed text comes out wrong | Jarvis says so when it can read the field back. Type in smaller pieces, or name the app exactly. |
| `click` cannot find a button you can see | Some apps (Electron, WebView2) hide their controls from UI Automation. "What does <app> say" lists what Jarvis can see. |
| A file is "blocked" | It is outside `[files] allowed_folders`, or its name looks like a secret (`.env`, `*.pem`). Add the folder in `config/local.toml`. |
| WhatsApp says "not sent" | `uv run jarvis whatsapp login` again if your phone unlinked it; if WhatsApp Web changed, set `[whatsapp] method = "desktop"` (R27). |
| "call mom" does nothing | Phone Link must be paired with calls on. The first `tel:` link asks which app opens it: pick Phone Link and "Always" (R36). |

## Notifications

| Symptom | Check |
|---|---|
| "Windows does not let Jarvis read notifications" | Settings, Privacy and security, Notifications: allow apps to access notifications. |
| WhatsApp messages never show up | The WhatsApp desktop app must run with notifications and message previews on, and "WhatsApp" must be in `[notifications] apps`. |
| An app you removed is still read | Not since Phase 9: taking an app off `[notifications] apps` deletes what was kept from it at the next read. |

## The Claude Code bridge

| Symptom | Check |
|---|---|
| Claude still asks in the terminal | `uv run jarvis claude-hook status`: the hooks must be installed and Jarvis running. No answer within `bridge.answer_timeout_s` (120 s) also leaves it to Claude. |
| `claude-hook test` says nothing was answered | Answer by voice after the question, or on the Jarvis page (it shows a card with a button per option). |
| A permission was not decided by voice | Only a clear yes or no counts ("yes", "allow it", "no"); anything else is left to Claude's own prompt, by design. |
| The phone never rings | `bridge.phone` is off by default. For ntfy set `phone.ntfy_topic` and install the ntfy app subscribed to it; permissions also need `NTFY_TOKEN`. For Twilio see SETUP.md 5i. |
| Turn it off | `uv run jarvis claude-hook uninstall`, or `[bridge] enabled = false`. |

## Routing and models

| Symptom | Check |
|---|---|
| A request without the usual words gets a web search | Semantic routing needs `nomic-embed-text` in Ollama (`ollama pull nomic-embed-text`); the log says "Semantic routing is off" when it is missing. |
| Answers got slower after a game | Ollama placed Hermes while the game held GPU memory; `ollama stop jarvis-hermes3` and the next command reloads it (R47). |
| I want faster answers and accept more mistakes | `[llm.providers.local] model = "llama3.2:3b"` in local.toml: 0.4 s instead of 2.7 s, 87% instead of 93% on the benchmark (ADR-061). |

## MCP servers and GitHub

| Symptom | Check |
|---|---|
| GitHub questions get a web search | `uv run jarvis mcp list`: the token must be in `.env`, and the server must start (`uv run jarvis mcp test github`). The request must mention GitHub, an issue, a pull request, a repo, or a commit. |
| "did not answer within 60s" | Docker Desktop is not running, or the image is still downloading: `docker pull ghcr.io/github/github-mcp-server:v2.0.2`. The server's own log is `%LOCALAPPDATA%\Jarvis\logs\mcp-github.log`. |
| "None of the tools listed exist" | The server renamed its tools; `uv run jarvis mcp tools github` shows the current names for `tools`. |
| It used the wrong owner for "my repo" | Say "remember that my GitHub username is ..." once. |
| A read asks for confirmation | The server is not `trusted`, or the tool is not marked read-only by the server. |
| GitHub answers are slow | Expected on the 8B model (R46); trim `tools` and `params`. |

## Mail and calendar

| Symptom | Check |
|---|---|
| "Email isn't set up yet" | `[mail] address` in local.toml and `MAIL_APP_PASSWORD` in `.env` (SETUP.md 5k); `uv run jarvis mail test`. |
| "The mail server refused the sign-in" | Use an app password, not your Google password; 2-Step Verification must be on. A new app password replaces a revoked one. |
| An email I just got is not listed | Only the inbox is read (`[mail] folder`), and "any new email" lists unread ones; say "my latest emails" to include read ones. |
| "Your calendar isn't set up yet" | `CALENDAR_ICS_URL` in `.env`; `uv run jarvis calendar test`. |
| "The calendar link answered 404" | The secret address was reset; copy it again from Google Calendar settings. |
| A new meeting is missing | Google refreshes the iCal feed on its own schedule, sometimes hours later (R44). |

## Dictation and media

| Symptom | Check |
|---|---|
| Ctrl+Alt+D does nothing | The startup banner says if another app owns the key; pick another under `[dictation] hotkey`. Dictation needs voice running (`jarvis serve`) and the microphone on in the tray. |
| "A key is still held down" | Let go of Ctrl and Alt within two seconds of releasing D; text typed with Ctrl held would act as shortcuts. |
| "That window runs as administrator" | Windows blocks typing into administrator windows from a normal app (R39). |
| The pasted text was your old clipboard | The app read the clipboard late; raise `paste_over_chars` so more text is typed instead. |
| A word came out wrong | Whisper `small.en` mishears names; there is no correction step. Spell it, or type it. |
| "Pause" started the music | That app has no Windows media session, so only the play/pause toggle key works (R40). |
| "What's playing" names the wrong app | Windows picks the current session when several apps play; pause the others. |

## Data

| Symptom | Check |
|---|---|
| "Jarvis's database was damaged" | The old file was kept as `jarvis.db.corrupt-<time>` and a fresh one started. Since ADR-048 this should not happen again on this Python; tell me if it does. |
| Jarvis's data is not in `%LOCALAPPDATA%\Jarvis` | You ran it with the Microsoft Store Python. Use `uv run jarvis ...` from the project folder (ADR-019). |
| A secret showed up in a reply | Values shaped like keys and `NAME=value` secrets are hidden as `[hidden]` (R38); one with no recognizable shape is not. Report the shape. |
