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

Fill in only the keys you use. `.env` is gitignored and must never be committed.

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
uv run jarvis chat --speak             # also speak every reply aloud (Windows SAPI voice)
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
| 6 | `uv run playwright install chromium` | Browser for Playwright tasks and WhatsApp Web |
| 8 | Kokoro extra | Bundle-safe voice for the packaged build (ADR-021) |

Voice models (Whisper, wake word, TTS voices) download on first use, or ahead of time with `uv run jarvis setup-voice`, into `%LOCALAPPDATA%\Jarvis\models`.

## 8. Where Jarvis keeps data

`%LOCALAPPDATA%\Jarvis\`

| Path | Contents |
|---|---|
| `jarvis.db` | Preferences, contacts, history, audit log, caches |
| `logs\` | Rotating log files |
| `models\` | Downloaded voice and wake word models |
| `browser-profile\` | Playwright profile with your WhatsApp Web login (treat as sensitive) |

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
