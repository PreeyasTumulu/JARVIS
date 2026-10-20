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
| Groq (optional) | Phase 8 | `GROQ_API_KEY` | Free plan, no card: about 1,000 requests a day for gpt-oss-120b |
| OpenRouter (optional) | Phase 8 | `OPENROUTER_API_KEY` | Free account: about 50 requests a day on free models |

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

## 5g. Notifications (Phase 7)

Nothing to install. Windows must allow apps to read notifications: Settings > Privacy & security > Notifications (on this laptop it already was). Jarvis reads only the apps you list, and keeps their text for a week:

```toml
[notifications]
apps = ["WhatsApp", "Claude"]   # display names, as the notification center shows them
keep_days = 7
```

```powershell
uv run jarvis notifications test    # shows a test notification Jarvis can read back
uv run jarvis ask "read my notifications"
uv run jarvis ask "anything new from Ravi"
uv run jarvis notifications         # what Jarvis has kept, newest first
```

While `jarvis chat`, `jarvis voice`, or `jarvis serve` runs, Jarvis checks every 2 s, so a WhatsApp notification that disappears when you read the message on your phone is still kept. Keep the WhatsApp desktop app running with notifications and message previews on, or there is nothing to read. Jarvis does not announce notifications; ask for them.

## 5h. Cloud model, memory, tray, and starting at login (Phase 8)

**Free cloud model (optional).** For heavy questions about public topics ("think harder: why did...", "explain the difference between..."), Jarvis can ask a bigger free model. Create free accounts at [console.groq.com](https://console.groq.com) and [openrouter.ai](https://openrouter.ai) (no card needed), make an API key in each, and put them in `.env` (copy `.env.example` if you have no `.env` yet):

```text
GROQ_API_KEY=gsk_...
OPENROUTER_API_KEY=sk-or-...
```

Without keys everything stays on the local model. Anything about your files, messages, notifications, clipboard, screen, apps, or memory always stays local. To use the cloud only when you say "think harder", set `[router] escalate = "explicit"`; `"never"` turns it off.

**Memory.** "Remember that my manager is Ravi", "who is my manager", "what do you remember about me", "forget that my manager is Ravi" (forgetting asks first). Memories stay in `jarvis.db`.

**Tray and login.**

```powershell
uv run jarvis serve --tray --wake --no-browser   # try the tray by hand
uv run jarvis startup enable                     # start like that at every login
uv run jarvis startup                            # is it on?
uv run jarvis startup disable
```

The tray icon is blue when ready, red while listening, amber while thinking, green while speaking, and grey with the microphone off. Click it to open the page; right-click for Microphone, Stop, and Quit. At login Jarvis starts through uv's windowless launcher (`uvw`), so no console window opens; its log is in `%LOCALAPPDATA%\Jarvis\logs`.

## 5i. Brave, the Claude Code bridge, your phone, and calls (Phase 9)

**Brave.** Jarvis's own browser follows your Windows default when it is Brave, Chrome, or Edge (`[browser] channel = "auto"`); your `local.toml` pins `channel = "brave"`. Links and site searches ("search youtube for lofi music") open in your normal Brave, where you are signed in. Jarvis's automated windows use their own profiles in `%LOCALAPPDATA%\Jarvis`, never your everyday Brave profile.

**Speech out for typed commands.** `[server] speak_replies = true` (set in your `local.toml`) makes Jarvis say the answer to anything typed on its page too, not only to what you said.

**"Hey Jarvis" check.** With no other Jarvis running:

```powershell
uv run jarvis voice --wake-test 30
uv run jarvis voice --train-wake        # if your "Hey Jarvis" scores stay under the threshold
```

It prints the microphone level and the wake word score every half second; say "Hey Jarvis" and look for `WAKE`. See [TROUBLESHOOTING.md](TROUBLESHOOTING.md) if it does not fire.

**Claude Code asks you through Jarvis.** While `jarvis serve` runs (it starts at login), Claude Code's multiple-choice questions and permission prompts can be answered by voice or on the Jarvis page, and Jarvis says when Claude is waiting or finished.

```powershell
uv run jarvis claude-hook test       # Jarvis asks a test question; answer by voice or on the page
uv run jarvis claude-hook install    # adds the hooks to ~/.claude/settings.json (a backup is kept)
uv run jarvis claude-hook status
uv run jarvis claude-hook uninstall
```

Answer a question with its number ("two") or its name; "other: ..." gives your own answer. Permissions need a clear "yes" or "no"; anything else, or silence for two minutes, leaves Claude to ask in the terminal as usual. `[bridge]` in `config/local.toml` turns parts off (`questions`, `permissions`, `announce`).

**Your phone (optional, off by default).** When nobody answers at the PC within `escalate_after_s` (45 s), the question can go to your phone. The question text then leaves this computer.

- ntfy (free): install the ntfy app ([ntfy.sh](https://ntfy.sh)) and subscribe to a long random topic, for example `jarvis-7f3k9q2m4x`. In `config/local.toml`:

  ```toml
  [bridge]
  phone = "ntfy"

  [phone]
  ntfy_topic = "jarvis-7f3k9q2m4x"
  ```

  You get an urgent notification with a button per option (up to three). Permissions go to the phone only with an access token in `.env` (`NTFY_TOKEN`), because anyone who knows a topic name can post to it.
- Twilio (paid, a real call): create an account, buy or verify a number, import [docs/twilio-ask-flow.json](twilio-ask-flow.json) as a Studio flow (Studio, Create new Flow, Import from JSON), then set `phone = "twilio"`, `[phone] number`, `twilio_from`, `twilio_flow_sid`, and `TWILIO_ACCOUNT_SID` and `TWILIO_AUTH_TOKEN` in `.env`. Press the option's number on the keypad, or say it.

**Calls through your phone.** Pair your Android phone in Phone Link with calls turned on (Bluetooth). Then "call mom" asks "Call Amma (number ending 3210) from your phone?" and, on yes, Phone Link dials. The first time, Windows asks which app opens phone links: pick Phone Link and "Always".

## 5j. Dictation and media (Phase 10)

```powershell
uv sync --extra voice --extra piper   # adds winrt-windows-media-control (a pip package, no system install)
uv run jarvis serve --wake
```

**Dictation.** Click where you want the text (a chat box, an email, VS Code), hold `Ctrl+Alt+D`, speak, and release. Say "comma", "full stop", "question mark", "new line", or "new paragraph" for punctuation and breaks; "um" and "uh" are dropped. Short text is typed; long text is pasted and your clipboard is put back, and it never shows up in Win+V history. A new line is Shift+Enter, so it never sends a chat message. Change the key or the rules under `[dictation]` in `config/local.toml`:

```toml
[dictation]
hotkey = "ctrl+alt+d"
paste_over_chars = 200     # 0 always pastes; a big number always types
spoken_commands = true
remove_fillers = true
```

**Media.** "Pause the music", "resume", "next song", "previous track", "skip this song", and "what's playing" run instantly, without the model. Anything else ("pause the video in Brave", "could you skip to the next track") goes to the model, which uses the same tools. It works with any app that shows up in the Windows volume flyout (Spotify, Media Player, YouTube in Brave); other apps get the keyboard's media keys.

## 5k. Mail and calendar (Phase 11)

**Mail (Gmail).** Jarvis signs in with an app password, not your real password.

1. Turn on 2-Step Verification for your Google account if it is off.
2. Open https://myaccount.google.com/apppasswords, create one named "Jarvis", and copy the 16 letters.
3. Put it in `.env` and your address in `config/local.toml`:

   ```
   MAIL_APP_PASSWORD=abcd efgh ijkl mnop
   ```

   ```toml
   [mail]
   address = "you@gmail.com"
   signature = "Preeyas"      # optional, added under replies
   ```

4. Check it (prints counts only):

   ```powershell
   uv run jarvis mail test
   ```

Then: "any new email?", "emails from Ravi", "read the second one", "reply that I'll send it tonight" (Jarvis reads the reply and the address back and sends only after your yes). Reading never marks anything as read. Outlook or Yahoo work too: set `imap_host` and `smtp_host` under `[mail]`.

**Calendar (Google Calendar).** Open Google Calendar on the web, Settings, pick your calendar under "Settings for my calendars", "Integrate calendar", and copy "Secret address in iCal format". Put it in `.env` (several calendars: separate the links with spaces):

```
CALENDAR_ICS_URL=https://calendar.google.com/calendar/ical/.../private-.../basic.ics
```

```powershell
uv run jarvis calendar test
```

Then: "what's on today", "my next meeting", "am I free on Friday", "what's on next week". Keep the link secret; "Reset" in the same place makes a new one.

## 5l. MCP servers and GitHub (Phase 12)

Jarvis can use tools from MCP servers. Each server is a section under `[mcp.servers]` in `config/jarvis.toml` (or your `local.toml`); only the tools listed there are given to the model, and they ask first unless the server marks them read-only and the section says `trusted = true`.

**GitHub** (already configured; needs Docker Desktop running):

1. Create a fine-grained personal access token at https://github.com/settings/personal-access-tokens: your repositories, read access to issues, pull requests, and contents (add write to issues only if you want Jarvis to open issues and comment).
2. Put it in `.env`:

   ```
   GITHUB_PERSONAL_ACCESS_TOKEN=github_pat_...
   ```

3. Check it, and tell Jarvis who you are on GitHub:

   ```powershell
   docker pull ghcr.io/github/github-mcp-server:v2.0.2
   uv run jarvis mcp list
   uv run jarvis mcp test github
   uv run jarvis ask "remember that my GitHub username is PreeyasTumulu"
   ```

Then: "any open issues on my JARVIS repo", "read issue 12 on JARVIS", "what were the last commits on JARVIS", "open an issue on JARVIS titled wake word misses quiet voices" (asks first).

**Another server** (for example one from https://github.com/modelcontextprotocol/servers):

```toml
[mcp.servers.home]
label = "Home Assistant"
url = "http://homeassistant.local:8123/api/mcp"
headers = { Authorization = "Bearer $HASS_TOKEN" }
keywords = ["light", "lights", "thermostat", "temperature", "living room"]
tools = ["HassTurnOn", "HassTurnOff", "GetLiveContext"]
```

`uv run jarvis mcp tools home` lists everything it offers, with which ones are read-only. Add `trusted = true` only for a server you trust to label its tools honestly, and `[mcp.servers.home.params]` to show the model fewer parameters.

## 5m. Faster speech recognition (Phase 13)

Whisper runs about ten times faster on the GPU. It needs NVIDIA's CUDA libraries as pip packages (about 1 GB, nothing system-wide):

```powershell
uv sync --extra voice --extra piper --extra gpu
uv run python scripts/voice_selftest.py      # "heard 'Open Notepad.' in about 130 ms"
```

`[voice] stt_device = "auto"` (the default) uses the GPU when it works and the CPU otherwise; `"cpu"` forces the CPU. To check which Whisper model suits your voice, read 30 commands once and compare (your recordings stay in `%LOCALAPPDATA%\Jarvis\stt-test`):

```powershell
uv run python scripts/benchmark_stt.py --record
uv run python scripts/benchmark_stt.py --mine --models small.en base.en medium.en --device cuda
```

Requests that use none of Jarvis's keywords ("what have I got lined up tomorrow") are routed by meaning with `nomic-embed-text`, which Phase 1 already pulled (`ollama pull nomic-embed-text` if not). Turn it off with `[agent] semantic_routing = false`.

## 5n. Recall and the morning briefing (Phase 14)

Nothing to install: both use `nomic-embed-text`, which is already pulled. For the briefing's weather, set your city in `config/local.toml`:

```toml
[weather]
home = "Hyderabad"
```

Then: "good morning" or "brief me" (weather, today's calendar and reminders, unread email and messages: counts and senders only), "what did I ask about Docker last week", "when did I check the weather". The first command each morning ends with an offer of the briefing; turn it off with `[briefing] offer = false`, or choose the parts with `parts = ["weather", "calendar"]`.

## 5o. Screen reading (Phase 15)

Nothing to set up: Windows OCR and its English language data come with Windows (check with `uv run python -c "from winrt.windows.media.ocr import OcrEngine; print([l.language_tag for l in OcrEngine.available_recognizer_languages])"`). Then: "what does this game window say" (read with OCR when the app shows no text to Windows), "click Save draft in ..." (asks first when it can only be found by reading the screen), "what's on my screen". Turn the fallbacks off with `[ui] ocr_fallback = false`.

## 6. Windows settings

| Setting | Path in Settings | Needed from |
|---|---|---|
| Microphone for desktop apps | Privacy and security, Microphone, "Let desktop apps access your microphone" | Phase 2 |
| Notification access | Privacy and security, Notifications, allow apps to access notifications (already on here) | Phase 7 |

Run Jarvis as your normal user, not as administrator. Windows blocks a normal process from automating elevated windows (Task Manager, admin terminals). That is intended.

## 7. Phase-specific installs

| Phase | Command | What it does |
|---|---|---|
| 2 | `uv sync --extra voice --extra piper` | faster-whisper, openWakeWord, sounddevice, Piper |
| 6 | `uv run playwright install chromium` | Only if you set `[browser] channel = "chromium"`; the default follows your default browser, Brave here (ADR-049) |

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
| `bridge.json` | While `jarvis serve` runs: the port and a random token the Claude Code hook uses (ADR-051) |
| `logs\claude-hook.log`, `logs\startup-hang.txt` | The hook's own log; where startup was stuck, if it ever was |
| `jarvis.db.corrupt-*` | Only after a damaged database was found at startup: the old file, kept untouched (ADR-043) |

None of this is inside the repository.

## 9. Troubleshooting

Moved to [TROUBLESHOOTING.md](TROUBLESHOOTING.md).
