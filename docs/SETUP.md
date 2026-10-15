# Setup guide

This guide grows with each phase. Steps marked with a phase number are not needed until that phase.

## 1. Verified environment

Checked on 2026-10-14 on the development laptop.

| Item | Found | Notes |
|---|---|---|
| OS | Windows 11 Home, build 26300 | |
| CPU | AMD Ryzen 7 6800H (8 cores, 16 threads) | Fast enough for CPU speech-to-text |
| RAM | 15.3 GB | Tight with Docker Desktop and an 8B model, see RISKS.md |
| GPU | NVIDIA RTX 3050 Laptop, 4 GB VRAM, driver 566.07 | `hermes3:8b` (4.7 GB) will not fit fully, Ollama splits it with the CPU |
| Free disk | 38.5 GB on C: | Enough for models (about 8 GB total) |
| Python | 3.12.10 (Microsoft Store build) | Not used by Jarvis: the Store build sandboxes AppData writes. The project uses a uv-managed Python 3.12 instead (ADR-019) |
| uv | 0.11.11 | Manages the project's Python and dependencies |
| Microphones | AudioRelay "Virtual Mic" is the Windows default (silent); Realtek "Microphone Array" picks up sound | `config/local.toml` sets `input_device = "Microphone Array"` |
| Ollama | 0.40.4 | Hermes 3 not pulled yet |
| Ollama models already present | llama3.2:3b, gemma3:4b, qwen3-vl, nomic-embed-text, smollm2 | `nomic-embed-text` is useful later for tool retrieval |
| git | 2.53.0 | Configured as PreeyasTumulu |
| GitHub CLI (gh) | Not installed | Repository created on github.com instead |
| VS Code CLI (`code`) | On PATH | Ready for the VS Code adapter |
| Docker CLI | Installed | Ready for the Docker adapter |
| Node.js | Installed | Not required |
| Everything CLI (`es.exe`) | Not installed | Optional, decided in Phase 3 |

## 2. Get the code

```powershell
git clone https://github.com/PreeyasTumulu/JARVIS.git
cd JARVIS
uv sync --extra voice --extra piper
```

`pyproject.toml` sets `python-preference = "only-managed"`, so uv downloads its own Python 3.12 the first time (about 30 MB, per user, no admin). Leave out `--extra voice --extra piper` if you only want text chat.

## 3. Local model (Phase 1)

```powershell
ollama pull hermes3:8b
ollama pull hermes3:3b
ollama create jarvis-hermes3 -f config/ollama/hermes3-8b.Modelfile
ollama create jarvis-hermes3-3b -f config/ollama/hermes3-3b.Modelfile
ollama run jarvis-hermes3 "Say hi in five words."
```

The Modelfiles set the context window (`num_ctx 8192`). Ollama's OpenAI-compatible endpoint ignores context length sent by clients, so it has to be set on the model. `ollama show jarvis-hermes3` should list `tools` under capabilities.

To switch Jarvis to the 3B model, set `model = "jarvis-hermes3-3b"` under `[llm.providers.local]` in `config/local.toml`, or try it for one session with `uv run jarvis chat --model jarvis-hermes3-3b`.

Recommended Ollama environment variables (System Properties, Environment Variables, then restart Ollama):

| Variable | Value | Why |
|---|---|---|
| `OLLAMA_KEEP_ALIVE` | `30m` | Keeps the model loaded, avoids a multi-second cold start per command |
| `OLLAMA_FLASH_ATTENTION` | `1` | Lower memory use for the context window |
| `OLLAMA_KV_CACHE_TYPE` | `q8_0` | Halves context memory, more of the model fits on the 4 GB GPU |

Check where the model runs with `ollama ps`. A split like `30%/70% CPU/GPU` is expected for the 8B model on this laptop.

## 4. Secrets

```powershell
Copy-Item .env.example .env
```

Fill in only the keys you use. `.env` is gitignored and must never be committed. Phase 4 works with no keys at all; a key adds a faster or more complete source and is picked up automatically.

| Service | Needed from | Key | Free tier (check current limits on signup) |
|---|---|---|---|
| Finnhub | Phase 4 | `FINNHUB_API_KEY` | Free key, per-minute limit, mostly US markets |
| Twelve Data | Phase 4 | `TWELVEDATA_API_KEY` | Free key, daily and per-minute limits |
| Alpha Vantage | Phase 4 | `ALPHAVANTAGE_API_KEY` | Free key, small daily limit |
| CoinGecko | Phase 4 | `COINGECKO_API_KEY` | Free demo key recommended |
| yfinance, Open-Meteo, Frankfurter | Phase 4 | none | No key needed |
| DeepSeek (optional) | Phase 8 | `DEEPSEEK_API_KEY` | Paid, only used if cloud escalation is enabled |

## 5. Your local config

```powershell
Copy-Item config/local.example.toml config/local.toml
```

Set your app allowlist, model choice, app aliases, microphone, hotkeys, and voice there (folder allowlist and home city arrive in later phases). `config/local.toml` is gitignored.

## 5a. Run it (Phase 1)

```powershell
uv run jarvis chat                     # interactive; Ctrl+C stops a command, /quit exits
uv run jarvis chat --speak             # also speak every reply aloud (Piper, or SAPI without it)
uv run jarvis ask "open notepad"       # one command, then exit
uv run jarvis audit --last 20          # recent tool calls with arguments and decisions
uv run pytest                          # unit tests (no Ollama needed)
uv run python scripts/benchmark_tools.py   # model accuracy and latency report
```

Developer hooks (optional): `uv run pre-commit install` runs ruff and the dash check before each commit.

## 5b. Voice (Phase 2)

```powershell
uv run jarvis setup-voice              # downloads Whisper small.en, the Piper voice, wake word + VAD (about 550 MB)
uv run jarvis voice --list-devices     # microphones; the Windows default is marked
uv run jarvis voice                    # push-to-talk
uv run jarvis voice --wake             # push-to-talk plus "Hey Jarvis"
uv run python scripts/voice_selftest.py            # wake word, VAD, and Whisper on synthesized speech
uv run python scripts/voice_selftest.py --agent    # same, then runs the command and speaks the reply
```

| Key or phrase | What it does |
|---|---|
| Hold `Ctrl+Alt+J` | Push-to-talk: speak after the beep, release when done. Also interrupts Jarvis while it talks |
| `Ctrl+Alt+X` | Stop: cancels the running command, speech, and any pending question |
| "Hey Jarvis" (with `--wake`) | Starts listening; Jarvis stops recording when you pause for 0.8 s |
| "stop", "cancel", "never mind" | Same as the stop key, handled without the model |
| "yes", "go ahead", "send it" | Approves a confirmation. Anything else, or silence, is a no. `y`/`n` on the keyboard also work |

Hotkeys are registered system wide while Jarvis runs. If one is taken by another app (on this laptop `Ctrl+Alt+Space` was), Jarvis says so at startup; pick another under `[voice]` in `config/local.toml`.

## 5c. Apps, files, and Docker (Phase 3)

```powershell
uv run jarvis index                    # rebuild the app and file indexes now (otherwise automatic)
```

- Jarvis only finds, opens, and reads files inside `[files] allowed_folders`. The defaults are `{documents}`, `{desktop}`, and `{downloads}`, which follow OneDrive (on this laptop Documents and Desktop live in `OneDrive`). `config/local.toml` adds `C:/Internships`. Lists replace, so keep the defaults when you add a folder.
- Optional: installing [Everything](https://www.voidtools.com/) (with its `es.exe` command line tool) makes file search instant and always current. Jarvis picks it up automatically.
- Optional: set VS Code's `window.title` to include `${activeEditorLong}` so "this file" always resolves to the exact path. Without it Jarvis looks the name up in the file index.
- Docker tools need the Docker engine running; Jarvis says so if it is not. Starting and stopping containers always asks first.

## 5d. Data and system tools (Phase 4)

```powershell
uv run jarvis ask "what's Reliance trading at"
uv run jarvis ask "bitcoin in rupees"
uv run jarvis ask "convert 100 dollars to rupees"
uv run jarvis ask "weather tomorrow"            # needs weather.home, see below
uv run jarvis ask "summarize https://www.python.org/about/"
uv run jarvis ask "set the volume to 30"
uv run jarvis chat                              # timers and reminders sound while chat or voice runs
```

- Put your city in `config/local.toml` under `[weather]` as `home = "Hyderabad"` (any city name Open-Meteo knows; "London, UK" style works for ambiguous names).
- `[market.aliases]` maps spoken names to tickers, for example `"reliance" = "RELIANCE.NS"`. `market.prefer_listings` picks NSE over a company's US share. Crypto prices default to `market.crypto_currency` (USD); say "in rupees" or set it to `"INR"`.
- Brightness works only for the laptop's own screen. Screenshots go to `Pictures\Screenshots` (`[system] screenshot_folder`).
- Reminders that came due while Jarvis was closed are announced as missed the next time it starts.

## 5e. Web UI (Phase 5)

```powershell
uv run jarvis serve                 # opens the page; voice and hotkeys run too if installed
uv run jarvis serve --wake          # also "Hey Jarvis"
uv run jarvis serve --no-voice      # page only
uv run jarvis serve --port 8800 --no-browser
```

- The page lives at `http://127.0.0.1:8765/?token=...`. The token changes every time Jarvis starts, so a bookmark stops working after a restart; use the link Jarvis opens or prints.
- The page is only reachable from this laptop. Other websites cannot talk to it (Origin, token, and Host checks).
- Enter sends, Shift+Enter adds a line, Esc stops. The mic button works like holding `Ctrl+Alt+J`: click, speak, click again. It uses the laptop's microphone, not the browser's, so the browser never asks for microphone access.
- Confirmations show as cards and are also asked aloud when voice is on. Answer either way; the first answer wins.
- `[server] port` and `open_browser` in `config/local.toml` change the defaults.

## 5f. Apps, the browser, contacts, and WhatsApp (Phase 6)

Nothing to install: UI automation uses Windows UI Automation, and Jarvis's browser is the Microsoft Edge that comes with Windows 11 (ADR-040).

**Typing and clicking in apps.** Say the app: "type hello world in Notepad", "click File in Notepad", "press ctrl s in Notepad", "what does the Notepad window say". Apps in `safety.trusted_ui_apps` (Notepad by default) run these without asking; everything else asks first. Messaging apps and terminals always ask; Registry Editor and password managers are blocked.

```toml
[safety]
trusted_ui_apps = ["Notepad", "Calculator"]
```

**Jarvis's browser.** "Search amazon.in for earbuds in your browser" opens Edge in Jarvis's own profile (`%LOCALAPPDATA%\Jarvis\browser-profile`), separate from your everyday browser. Do not sign in to personal accounts there unless you want Jarvis to work in them. Submitting forms and buying ask first; it never types passwords or card numbers.

**Contacts.** Add the people you message, with the names you call them:

```powershell
uv run jarvis contacts add "Amma" "+91 98765 43210" --alias Mom --alias Mummy
uv run jarvis contacts add "Ravi Kumar" "+91 90000 00001" --alias Ravi
uv run jarvis contacts alias "Ravi Kumar" RK
uv run jarvis contacts import C:\Users\you\Downloads\contacts.vcf
uv run jarvis contacts                      # list them
uv run jarvis contacts remove "Ravi Kumar"
```

The web page has the same in its Contacts tab, including .vcf import. To export a .vcf on Android: Contacts app, Fix and manage (or Settings), Export to file. Numbers saved without a country code need one setting:

```toml
[contacts]
default_country_code = "91"
```

**WhatsApp.** You accepted the account risk in RISKS.md R5. Until WhatsApp Web is linked, Jarvis uses the WhatsApp desktop app (installed from the Microsoft Store). To use WhatsApp Web, which can also confirm delivery, link it once:

```powershell
uv run jarvis whatsapp login      # scan the QR code: phone, WhatsApp, Settings, Linked devices
```

Then say "message Mom that I'll be late". Jarvis reads the message back with the contact's name and the last digits of the number, and sends only after you say or click yes. Silence or "no" sends nothing. To force one way, set `[whatsapp] method = "web"` or `"desktop"`.

## 6. Windows settings

| Setting | Path in Settings | Needed from |
|---|---|---|
| Microphone for desktop apps | Privacy and security, Microphone, "Let desktop apps access your microphone" | Phase 2 |
| Notification access | Privacy and security, Notifications, allow apps to access notifications | Phase 7 |

Run Jarvis as your normal user, not as administrator. Windows blocks a normal process from automating elevated windows (Task Manager, admin terminals). That is intended.

## 7. Phase-specific installs

| Phase | Command | What it does |
|---|---|---|
| 2 | `uv sync --extra voice --extra piper` | faster-whisper, openWakeWord, sounddevice, Piper |
| 6 | `uv run playwright install chromium` | Only if you set `[browser] channel = "chromium"`; the default uses Edge (ADR-040) |
| 8 | Kokoro extra | Bundle-safe voice for the packaged build (ADR-021) |

Voice models (Whisper, wake word, TTS voices) download on first use, or ahead of time with `uv run jarvis setup-voice`, into `%LOCALAPPDATA%\Jarvis\models`.

## 8. Where Jarvis keeps data

`%LOCALAPPDATA%\Jarvis\`

| Path | Contents |
|---|---|
| `jarvis.db` | Preferences, contacts, history, audit log, app and file indexes, API cache, reminders |
| `logs\` | Rotating log files |
| `models\` | Downloaded voice and wake word models |
| `browser-profile\` | Jarvis's browser profile (cookies of sites it visited) |
| `whatsapp-profile\` | WhatsApp Web, linked to your phone (treat as sensitive; unlink from your phone and delete it to remove) |
| `jarvis.db.corrupt-*` | Only after a damaged database was found at startup: the old file, kept untouched (ADR-043) |

None of this is inside the repository.

## 9. Troubleshooting

| Symptom | Check |
|---|---|
| "Connection refused" to the model | Is Ollama running? Open `http://localhost:11434` in a browser. |
| Very slow replies | `ollama ps` shows the CPU/GPU split. Close GPU-heavy apps, try `hermes3:3b`. |
| The model answers in text instead of calling a tool | Make sure you are using the `jarvis-hermes3` model and Ollama is up to date. |
| "is sending pure silence" at voice startup | The selected mic is muted or virtual. `uv run jarvis voice --list-devices`, then set `input_device` in `config/local.toml`. |
| Jarvis never hears you | Windows privacy setting "Let desktop apps access your microphone", and the device above. |
| "Could not register" a hotkey | Another app owns that combination. Change `ptt_hotkey` or `stop_hotkey` under `[voice]`. |
| Jarvis's data is not in `%LOCALAPPDATA%\Jarvis` | You ran it with the Microsoft Store Python. Use `uv run jarvis ...` from the project folder (ADR-019). |
| Wake word triggers by itself | Raise `wake_threshold` under `[voice]` (default 0.5). |
| "Jarvis's browser did not start" | Edge must be installed (it is part of Windows 11). With `channel = "chromium"`, run `uv run playwright install chromium`; on some Windows builds that Chromium fails with "side-by-side configuration is incorrect" (RISKS.md R23). |
| Typed text comes out wrong in an app | Jarvis says so when it can read the field back. Type in smaller pieces, or tell the app's name exactly. |
| `click` cannot find a button you can see | Some apps (Electron, WebView2) hide their controls from UI Automation. `what does <app> say` lists what Jarvis can see. |
| WhatsApp says "not sent" | `uv run jarvis whatsapp login` again if the phone unlinked it; if WhatsApp Web changed, set `[whatsapp] method = "desktop"` (RISKS.md R27). |
| "Jarvis's database was damaged" | The old file was kept as `jarvis.db.corrupt-<time>` and a fresh one started. Indexes rebuild themselves; history and audit restart. |
