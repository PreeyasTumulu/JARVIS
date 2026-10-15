# Risks and Windows reliability

Things that are unreliable, fragile, or risky, written down before building so they are handled on purpose instead of discovered later. Each risk has a mitigation and the phase where it matters.

## Risk register

| # | Risk | Likelihood | Impact | Mitigation | Phase |
|---|---|---|---|---|---|
| R1 | Hermes 3 8B does not fit in 4 GB VRAM, replies are slow | High | Medium | KV cache quantization, keep-alive, stable prompt prefix, benchmark against `hermes3:3b`, fast path for "stop" | 1 |
| R2 | A small model picks the wrong tool or wrong arguments | Medium | Medium | Policy gate, confirmations, argument validation, benchmark suite, tool retrieval if accuracy drops | 1, 4 |
| R3 | 16 GB RAM is tight with LLM, Whisper, Playwright, Docker Desktop, and your own apps | Medium | Medium | STT on CPU with a small model, DuckDuckGo instead of SearXNG, lazy-load voice and browser components | 2, 6 |
| R4 | Notification listener does not work from unpackaged Python | Spike passed | High for Phase 7 | Spike done (reading and polling work, events do not); poll and diff by id, app allowlist, WhatsApp Web polling only as a fallback | 7 |
| R5 | WhatsApp automation breaks or risks the account | Medium | High | You accepted the risk (ADR-037); read back and explicit yes on every send, low volume, WhatsApp's own click-to-chat links, selectors in one file, desktop fallback, never two sends | 6 |
| R6 | UI automation is flaky on some apps | High | Medium | Prefer CLI adapters, UIA only where needed, paced typing read back afterwards, focus checked before every burst, clear failure messages | 6 |
| R7 | Prompt injection from web pages, files, or notifications | Medium | High | Untrusted-data wrapping, policy gate in code, confirmations cannot be answered by tool content | All |
| R8 | Wake word false triggers, especially from Jarvis's own voice | Medium | Low | Pause wake word while speaking, threshold tuning, push-to-talk as the reliable path | 2 |
| R9 | Unofficial data sources (yfinance, ddgs) change or rate limit | High | Low | Provider fallback chains, caching, circuit breakers | 1, 4 |
| R10 | Other websites talking to the local UI | Low | High | 127.0.0.1 bind, Origin check, per-launch token, Host check, no framing (ADR-035); verified against the running server | 5 |
| R11 | A stuck Windows call cannot be cancelled instantly | Medium | Low | Cooperative cancellation, per-tool timeouts, work isolated on worker threads | 1, 6 |
| R12 | Private data reaches a cloud model | Low | High | Sensitivity labels, fresh public-only cloud context, guard that raises, dedicated tests | 8 |
| R13 | Microsoft Store Python hides Jarvis's data (AppData redirection) | Happened | Medium | uv-managed Python only (ADR-019), CLI warning, data moved | 2 |
| R14 | Wrong or silent microphone, hotkeys owned by other apps | Happened | Medium | Startup mic silence check, `--list-devices`, name-based device selection, hotkey conflict warnings | 2 |
| R15 | The model misreads tool data in its answer (said a stopped container was running) | Medium | Low | Short summaries computed in code, ask for details when it matters; revisit with a larger or cloud model | 3 |
| R16 | Tool choice degrades as tools are added (80% with 16 tools, 67% with 31, 77% with 40, where most misses are empty replies to the long prompt) | Happened | Medium | Keyword routing (87% in Phase 3, 89% in Phase 4, 91% in Phase 6), clear tool descriptions, errors that guide a retry, a retry for empty replies, benchmark per phase | 3, 4, 6 |
| R17 | Prompt injection leaks private data through a web request | Low | High | `egress` tools confirm when private data and outside content are both in context (ADR-029), local addresses blocked | 4 |
| R18 | Brightness control only reaches the built-in screen | Certain | Low | WMI covers laptop panels; external monitors get a clear message instead of a fake success | 4 |
| R19 | Reminders do not sound when Jarvis is not running | Certain | Medium | Missed reminders are announced at the next start; start at login in Phase 8 | 4, 8 |
| R20 | Market data is delayed, or wrong for an ambiguous name | Medium | Low | Providers report the latest price they have; the spoken name says which company was used; aliases in config | 4 |
| R21 | Output redirected to a pipe or file crashed on non-ASCII text (cp1252) | Happened | Medium | The CLI switches redirected output to UTF-8 at startup | 5, 8 |
| R22 | The page shows private data (files, clipboard, audit log) to whoever uses the browser | Medium | Medium | Local only, per-launch token; lock the laptop when you leave it | 5 |
| R23 | Playwright's Chromium does not start on this Windows build | Happened | Medium | Edge is the default browser (ADR-040); Chromium stays an option | 6 |
| R24 | The database lost pages and stopped accepting audit entries | Happened | High | Quick check at every start, damaged file kept and rows salvaged (ADR-043) | 6 |
| R25 | An 8B model does not chain browser steps, and claims steps it did not do | Happened | Medium | Open and search in one call (ADR-038), a hint after each step, the tool log shows what really ran | 6 |
| R26 | Websites block or challenge automated browsers | Medium | Low | Jarvis reports the page as it is and never tries to get past a bot check or CAPTCHA | 6 |
| R27 | A WhatsApp Web update breaks sending | High | Medium | Selectors in one file, nothing is sent unless the message is seen in the box first, desktop fallback | 6 |

## Details

### R1. Hardware budget for the local model

- `hermes3:8b` is 4.7 GB at its default quantization. The RTX 3050 Laptop GPU has 4 GB, so Ollama will put part of the model on the CPU. Expect noticeably slower generation than a model that fits fully.
- Prompt processing matters as much as generation. Tool schemas add a few thousand tokens to every request. Keeping the system prompt and tool list identical within a session lets Ollama reuse its cache.
- Phase 3 replies: list-shaped tool results made the 8B model write long markdown lists (40 to 60 s of generation). Spoken summaries and a reply instruction brought this down to a few seconds (ADR-027).
- `hermes3:3b` (2.0 GB) fits on the GPU and is faster, but in the Phase 1 benchmark it produced malformed tool calls (the function name in the arguments field, no tags) and called no tools at all. See [benchmarks/phase1.md](benchmarks/phase1.md).
- Measured in Phase 1: `hermes3:8b` picks the right tool on 20 of 20 test commands at about 3 seconds per model call, so a typical command (tool call, then a spoken answer) takes 5 to 7 seconds. The Ollama settings in SETUP.md (flash attention, q8_0 KV cache) should move more of the model onto the GPU.
- faster-whisper on the GPU would compete for the same 4 GB, which is why STT runs on CPU by default.

### R4. Notifications (Windows UserNotificationListener)

What is known before the spike:

- Windows exposes notifications through `UserNotificationListener`. Access requires your explicit permission, and a denial is sticky: after "Denied", only the Settings app can re-enable it ([RequestAccessAsync docs](https://learn.microsoft.com/en-us/uwp/api/windows.ui.notifications.management.usernotificationlistener.requestaccessasync)).
- Developers using unpackaged desktop apps (WinForms, WPF) report that access returns "Allowed" but subscribing to the `NotificationChanged` event fails with "Element not found" (0x80070490), and that the fix was packaging the app with MSIX ([report 1](https://windows-hexerror.linestarve.com/q/so66083903-c-net-usernotificationlistener-element-not-found), [report 2](https://windows-hexerror.linestarve.com/q/so66657872-access-to-windows-notification-from-wpf)).
- Polling with `GetNotificationsAsync` ([docs](https://learn.microsoft.com/en-us/uwp/api/windows.ui.notifications.management.usernotificationlistener.getnotificationsasync)) is the more likely path for a Python process. A Python example using pywinrt with the listener exists ([Zenn article](https://zenn.dev/sharl/articles/2bd2ff1ee51db4)), but none of this is verified on this laptop yet.

Other limits:

- Only notifications still in the notification center are visible. Dismissed ones are gone.
- Apps that disable notifications or hide previews (WhatsApp has a setting for this) give Jarvis nothing to read.
- The listener sees **every** app's notifications, including OTPs and bank alerts mirrored from your phone. Jarvis will filter by an app allowlist and treat everything as private.
- Notification text can contain messages written by other people. It is always data, never instructions.

If the spike fails: options are an MSIX "sparse package" to give the Python process an identity (complex), or WhatsApp-only notifications by polling unread chats in WhatsApp Web.

**Spike results (2026-10-15, this laptop, Windows 11 build 26300, pywinrt 3.2.1, `scripts/spike_notifications.py`):**

| Check | Result |
|---|---|
| `get_access_status()` | `ALLOWED` already, so no prompt was shown and `request_access_async()` was not needed |
| `get_notifications_async(TOAST)` | 29 notifications from 4 apps in 70 ms; title and text readable for every one |
| Own test toast | read back exactly (app "Windows PowerShell", both text lines) |
| Poll and diff by id, every 0.5 s | a new toast was seen 0.6 s after it was shown |
| `add_notification_changed` | fails with 0x80070490 "Element not found", as reported for unpackaged apps |
| WhatsApp desktop | its notifications carry two text lines (chat or sender, then the message), so previews are on; app id `5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App` |
| Removing a notification | works for the spike's own toasts |

The spike printed only counts per app and text lengths, never other apps' text. What it means: reading works from plain Python and polling is fast enough, so no MSIX package is needed; the event subscription is not available, so changes must be found by polling. Notifications stay in the center for days (the oldest here was three days old), so the first poll after a start sees a backlog, which Jarvis must treat as "already there", not new.

### R5. WhatsApp automation

- WhatsApp's terms do not allow automated or unofficial clients. Automating WhatsApp Web carries a real, if small for low-volume personal use, risk of the account being restricted or banned. You accepted this at the start of Phase 6 (ADR-037).
- WhatsApp Web's page structure changes without notice, which breaks selectors. They are kept in `tools/messaging/selectors.py`. The signed-in selectors (message box, Send button, sent message, ticks) were written against a stand-in page (`tests/fixtures/whatsapp_web.html`) and are unconfirmed until your first real send; the logged-out page (the QR code) was checked against the real site in Edge.
- Jarvis only presses Send after it sees exactly your message in the box, and falls back to the desktop app only when Web never got that far, so a broken selector means "not sent", never "sent twice".
- The desktop fallback uses the `whatsapp://send` link, which needs the contact's phone number, and presses Enter only after your yes and after reading the message box through UI Automation. That read was not exercised live (it would need a real chat), and the app cannot say whether the message was delivered.
- WhatsApp Web lives in its own profile, `%LOCALAPPDATA%\Jarvis\whatsapp-profile`, which holds a logged-in session. Anyone with that folder can read your chats. It is never in the repository, and the browser the model drives (`browser-profile`) never shares it. To unlink, remove the device in WhatsApp on your phone (Linked devices) and delete the folder.
- Groups and contacts without a phone number cannot be messaged yet.

### R6. UI automation quirks on Windows

- **Elevated windows:** a normal process cannot automate windows running as administrator (UIPI). Jarvis runs as a normal user by design.
- **Electron and web-based apps** (VS Code, Claude desktop, Docker Desktop, many others) expose thin or incomplete accessibility trees. CLI adapters and keyboard shortcuts are preferred for them.
- **Focus stealing protection:** Windows sometimes refuses to bring a window to the front, so focus can silently fail. Jarvis verifies focus after each attempt.
- **DPI scaling:** coordinate-based PyAutoGUI clicks are wrong unless the process is DPI aware. Jarvis sets DPI awareness at startup and uses coordinates only as a last resort.
- **Secure desktop:** UAC prompts and the lock screen cannot be automated at all. That is a Windows security boundary.
- **COM threading:** pywinauto and Shell COM objects must stay on one thread with COM initialized. All UI work runs on a single dedicated worker thread.
- **Generic clicks are hard to risk-rate:** a "click" can press Send or Delete. Generic UI tools require confirmation except inside apps you mark as trusted, and destructive-looking targets always confirm. This is a heuristic, not a guarantee.
- **Typing speed (measured in Phase 6):** Windows 11 Notepad reads input late. Unicode characters sent in a burst arrive as the last one repeated ("hello world" became "hello ddddd"), and real key presses lose their Shift ("Typing" became "tping"). Jarvis types one character every 12 ms (80 ms after an emoji), about 75 a second, then reads the field back and tells you if the text does not match. Apps that do not expose their text cannot be checked, and Jarvis says it typed without having checked.
- **Focus can move while typing:** if another window comes to the front, typing stops at the next burst of 24 characters and says how far it got, so the rest never lands in the wrong window. Up to one burst can still land before that check.
- **Apps that hide their controls:** Electron and some WebView2 apps expose few named controls, so `click` may not find a button you can see. `read_window_text` lists what UI Automation reports.

### R7. Prompt injection

Any text Jarvis reads (web pages, files, window text, notifications, clipboard) can contain instructions aimed at the model. The defenses, in order of strength:

1. Side effects need a confirmation that only you can give, through a UI button, the CLI, or your voice.
2. Blocked actions cannot be unblocked by anything the model says.
3. When private data and outside content are both in the conversation, requests to addresses the model picks (`fetch_page`, `open_url`) need your confirmation (ADR-029).
4. Untrusted results are wrapped and tag-escaped, and the system prompt says they are data.
5. Cloud turns never see private content.

What is not covered: an injected instruction can still trigger `safe` actions that leak nothing, such as opening an allowlisted app, changing the volume, or putting text on the clipboard (`clipboard_write`). Pasting something you did not copy yourself into a terminal is the realistic danger there, so look before you paste.

### R8. Audio

- No acoustic echo cancellation is planned, so Jarvis's own voice can trigger the wake word. Wake word detection pauses while it speaks. Barge-in uses the push-to-talk hotkey.
- Whisper `small.en` handles Indian English well in general, but names of people and Indian companies may be misheard. Contact and ticker aliases help, and a multilingual model is a config option.
- Phase 2 was verified with synthesized speech (Windows SAPI voice) through the real models, not with a person talking into the laptop's microphone. Real-room accuracy, wake word false triggers, and the 0.8 s end-of-speech pause need your testing and probably some tuning (`wake_threshold`, `vad_threshold`, `end_silence_ms`).
- On this laptop the Windows default input is AudioRelay's virtual microphone, which is silent unless the phone app streams to it, and the ASUS noise-cancelling input was also silent during setup. `config/local.toml` points Jarvis at the Realtek array. Jarvis checks the level at startup and warns about a silent device.
- The ASUS "AI Noise-cancelling Input" may become the better choice once the ASUS app is running, because it removes background noise before Whisper hears it.

### R23. Playwright's Chromium on this Windows build

Playwright's Chromium builds 1243 and 1248 fail to start on this laptop (Windows 11 build 26300) with "The application has failed to start because its side-by-side configuration is incorrect"; the Event Log says the private assembly named after the Chromium version "could not be found", though the manifest file is next to `chrome.exe`. It fails inside and outside the command sandbox, so it is the Windows build, not Jarvis. Edge, through Playwright's `msedge` channel, works, and is now the default (ADR-040). If a Windows update fixes this, `[browser] channel = "chromium"` brings Playwright's build back. The unused download sits in `%LOCALAPPDATA%\ms-playwright\chromium-1248` (about 440 MB) and can be deleted.

### R24. The database lost pages

During Phase 6 testing, `jarvis.db` turned out damaged: SQLite could still list the tables, but the pages holding the file index (20,059 rows), the command history, and the audit log were gone from the file, and new audit entries failed with "database disk image is malformed". Jarvis kept answering but logged the failures only to its log file. The cause could not be pinned down: no Jarvis code path writes after closing, tests never touch the real data folder, and the history shows writes working until the last run before the error. The most likely explanation is the write-ahead log being lost while several Jarvis processes, started from different shells during development, used the database. Jarvis now checks the file at every start and moves a damaged one aside, keeping it untouched and copying every readable row into a fresh database (ADR-043). On this laptop that ran once: nothing was readable, so history and audit start fresh, and the damaged file is kept as `jarvis.db.corrupt-20261015-134134`.

### R25. Small models and multi-step browsing

Hermes 3 8B reliably makes one tool call per request, but after `browser_open` it usually answers instead of calling `browser_type`, and it then says it searched when it did not (three live attempts). "Open this site and search it" is therefore one call (`browser_open` with `search`). Longer flows (search, open a result, add to cart) are unreliable at this size; the tool log shows what really ran, so a claimed step that did not happen is visible. A larger model (Phase 8 cloud escalation, for public pages only) is the fix.

### R26. Websites and automated browsers

Jarvis's browser is visibly automated (Playwright marks it, and it starts with a fresh profile). Some sites answer with a bot check, a CAPTCHA, or a sign-in wall. Jarvis reports what the page shows and never tries to get past a bot check or solve a CAPTCHA. Amazon.in served its normal page in testing.

### R27. WhatsApp Web updates

WhatsApp Web changes without notice. When sending breaks, Jarvis says it did not send (it never presses Send without first seeing the message in the box), and `[whatsapp] method = "desktop"` switches to the desktop app until the selectors in `tools/messaging/selectors.py` are fixed.

### R11. Cancellation

Python cannot kill a thread. Tools running on worker threads (UI automation, file indexing) check the cancel token between steps and have timeouts. The agent returns control to you immediately on "stop", even if a background step takes a moment to wind down.
