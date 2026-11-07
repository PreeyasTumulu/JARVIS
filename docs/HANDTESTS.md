# Hand tests

Each phase is tested by hand on the laptop, not only with unit tests. Every row is one command given to a real `jarvis chat` with the local model (Hermes 3 8B on Ollama), a scratch data folder (`LOCALAPPDATA`), and a copy of the config (`JARVIS_CONFIG_DIR`), so the test never touches your own history, contacts, or messages. A row that needs something only you can do (a real lock, your voice, a real call) says so and stays open until you run it.

The harness that drives `jarvis chat` through pipes is `scripts/drive_chat.py`, described in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Phase 19: Privacy

Run on 2026-11-05.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 19.1 | "what's the weather in Hyderabad" | weather is read | `weather(place="Hyderabad")`, 22 degrees, overcast | pass |
| 19.2 | "forget what I asked about the weather" | asks first, says how many | confirm card: "Delete 1 past command (today), such as ..."; answered y; "Okay, I've deleted that command." | pass |
| 19.3 | "what did I ask about the weather" | finds nothing | `recall` found nothing: "I have no commands from today." | pass |
| 19.4 | database after 19.2 | the command is gone from history, vectors, and audit, and the forget request is not kept | `command_history` holds only 19.3, `embeddings` is empty, the only audit rows are the deletion itself (args `id:1`, no words) and 19.3 | pass |
| 19.5 | "remind me in one minute to stretch", then lock the PC | while locked it says only that something is waiting; after unlock it says the reminder | not run: unlocking needs your PIN | needs you |

## Phase 20: Clipboard history and focus sessions

Run on 2026-11-05 with `[clipboard] history = true`.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 20.1 | copy "jarvis test alpha", then "jarvis test bravo" | both kept, newest first; what was on the clipboard before Jarvis started is not kept | `clipboard_history`: bravo at 1, alpha at 2, nothing else | pass |
| 20.2 | "what did I copy earlier" | lists them | "The most recent one was "jarvis test bravo" and the one before that was "jarvis test alpha"." | pass |
| 20.3 | "put the second last thing I copied back on the clipboard" | alpha is on the clipboard | `clipboard_restore(position=2)`; the clipboard held "jarvis test alpha" | pass |
| 20.4 | "start a focus session for 2 minutes", then "remind me in one minute to stretch" | nothing at one minute; at two, it says the session is over and that one reminder waited, then the reminder | first run: the reminder was held until the end (due 2:20, said 2:21:46), but the summary was never shown in the chat, and it was spoken at the same moment as the reminder | **fail** |
| 20.4 (after fix) | same | same | due 2:29, nothing said until 2:30:11; then "Your focus session is over, after 2 minutes. 1 reminder waited." and then "Reminder: stretch." | pass |
| 20.5 | press Ctrl+V into your own app after 20.3 | pastes "jarvis test alpha" | not run: pasting into one of your apps | needs you |

**Fixed in 20.4 (Phase 21 branch):** the end of a focus session was only handed to the speech engine, so a text chat never showed it, and the reminder it had held fell due at the same moment and was spoken over it (neither SAPI nor Piper queues). The summary is now an `Announcement` event the console prints, and Jarvis's own announcements are spoken one at a time, the summary first. Test: `test_the_end_is_shown_first_and_spoken_before_the_held_reminder`.

## Phase 21: Speed and coverage

Run on 2026-11-05.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 21.1 | "what's 10 + 10" | "20", no model call | `calculate(expression="10 + 10")`, "20", no model line, 0 ms | pass |
| 21.2 | "what is 2 to the power of 16" | "65536", no model call | `calculate(expression="2 ** 16")`, "65536", no model line | pass |
| 21.3 | "what's a 15 percent tip on 840 rupees" | the model uses `calculate` | one model call (3.3 s), `calculate(expression="15/100*840")`, "126" | pass |
| 21.4 | "what's 5 divided by 0" | a clear refusal, no crash | `calculate` failed with "You can't divide by zero.", said as such | pass |
| 21.5 | `jarvis chat` start and `/quit`, three runs | measured | 2.54 s, 2.50 s, 2.56 s | measured |
| 21.6 | `pytest --cov` | at least 78 percent | 78 percent of 11,799 statements, 966 passed | pass |

## Phase 32: The chat window, live

Run on 2026-11-07 with a real `jarvis serve --no-voice` on a scratch data folder and config, in the browser pane.

| # | Check | Expected | Actual | Result |
|---|---|---|---|---|
| 32.1 | open `http://localhost:8799/` | the page connects | "Connected to Jarvis on this computer", mic greyed out (voice off) | pass |
| 32.2 | type "what is 15 times 12" | the answer | "180" | pass |
| 32.3 | type "open paint", answer No | a card from the gate, nothing opens | "Open Paint? (Paint is not in the app allowlist)", then "You said no." and "Okay, I won't." | pass |
| 32.4 | reload | the turns come back | all four messages back | pass |
| 32.5 | "what is the capital of France" (Hermes) | the states in order, a reply | thinking, tool, thinking, speaking, idle in 13 s; "The capital of France is Paris." | pass |
| 32.6 | a long request, then Stop | stopped once, back to idle | "Stopped." twice and then the error state | **fail**, fixed: once, then idle |
| 32.7 | stop serve, start it again | the window says it is down, then the same token works | the down note shown; the page token matched the saved one after the restart | pass |
| 32.8 | `/` with `Sec-Fetch-Site: cross-site`; a foreign Host | refused | 403; 400 | pass |
| 32.9 | the window command | Brave in app mode | `brave.exe --app=http://127.0.0.1:8765/ --window-size=480,800` (not launched) | pass |

| 32.10 | `jarvis ui` against a running serve (scratch data) | a Brave app window that connects | "Opened the chat window in brave", a window titled "Jarvis chat", a second client in the log | pass |
| 32.11 | typed "open Jarvis" | the exact phrase opens another window | "Opening the chat window.", two Jarvis chat windows | pass |
| 32.12 | `voice_selftest.py --agent` with "what is the capital of France" (scratch data) | wake word, endpoint, Whisper, agent, spoken reply | wake 0.99 at +51 ms, end of speech +756 ms, text in 196 ms, web search, "The capital of France is Paris." spoken | pass |
| 32.13 | KDE Connect state | paired | still visible but not paired | needs you |

**Needs your hands:** the mic button with voice on, "open Jarvis" by voice, and pairing the phone.

## Phase 31: Open-source readiness

Run on 2026-11-07.

| # | Check | Expected | Actual | Result |
|---|---|---|---|---|
| 31.1 | scan the tracked files by hand | nothing personal | the phone's real model in the demos, tests and docs, its real Wi-Fi address in a comment and tests, your first name as an SSH user in a test | **fail**, replaced with made-up values |
| 31.2 | `git log --all -p` for keys and +91 numbers | only fakes | only the test fakes | pass |
| 31.3 | `scripts/check_personal.py` | passes on the clean repo, catches real-looking values | 5 hits on its first run, all resolved; 8 real-looking samples caught and 8 known fakes passed in the tests | pass |
| 31.4 | `.env.example` against the code | every key listed | all 14 present | pass |
| 31.5 | `scripts/make_demo_gif.py` | a small looping GIF with every state's colours | first try: one frame's palette turned the idle orb and the blue listening state grey; with one palette from frames across the run, 172 frames, 1.4 MB | pass after fix |

## Phase 30: UI demos

Run on 2026-11-07 in the browser pane and with Playwright on Edge.

| # | Check | Expected | Actual | Result |
|---|---|---|---|---|
| 30.1 | the scripted run on the reactor | idle, listening with words appearing, thinking, waiting for your yes | first try stayed in idle (a step's milliseconds were added to a clock in seconds); after the fix it ran through | **fail**, pass after fix |
| 30.2 | frozen frames for screenshots | the page draws one fixed picture | the browser pane timed out on pages that stopped drawing; they now keep drawing the same frame | pass after fix |
| 30.3 | all 42 states at 1000 by 625 | every state reads clearly | the pill's question stretched and pushed Yes and No to the bottom; the edge glow looked like a hard frame; the terminal said "ok" for a failed tool | three fixes, pass |
| 30.4 | the confirmation state at 390 by 844 | fits a phone | all six fit, with nothing cut off | pass |
| 30.5 | a state button, then Yes, then key 7 | pauses the run, Yes leads to the tool and then speaking, 7 shows the error | confirm, "Play the demo", tool `send_to_phone`, speaking, error | pass |
| 30.6 | console errors | none | none | pass |

| 30.7 | `chat.html` in all seven states, light and dark, desktop and phone | each state readable, the orb in the right place | the glow's wide second ring left a hard inner rectangle on a phone, and an answered card was an empty box; replaced by an inset bloom and a quiet line | pass after fix |
| 30.8 | `chat.html` live: type "send the clipboard to my phone", Yes, then the mic, then New chat | confirmation, tool, reply word by word, a spoken turn, the orb back in the middle | as expected, no page errors | pass |

**Needs your hands:** "Use my microphone" with your own microphone, and `/review-animations` on `ui-demos/chat.html` if you want the motion review skill's report.

## Phase 29: Your phone, for free

Run on 2026-11-07 on a scratch data folder. The phone was visible to KDE Connect but not paired, so nothing reached it; the ntfy pushes went to a throwaway random topic and were read back from ntfy.sh.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 29.1 | real `kdeconnect-cli --list-devices` through the adapter | the phone, its state | the phone by name, reachable, not paired, in 2.1 s (`--list-available` printed none) | pass |
| 29.2 | `ring_phone`, `notify_phone` with the phone unpaired | nothing sent; how to pair | "on the Wi-Fi but not paired: open KDE Connect on the PC, choose it, press Pair, and accept on the phone" | pass |
| 29.3 | `Phone.alert(ring=True)` by ntfy to a random topic | priority 5, read back | 0.75 s; read back with title "Jarvis", priority 5 | pass |
| 29.4 | "find my phone" | exact phrase, no model | handled_by exact_phrase, `ring_phone` | pass |
| 29.5 | "remind me on my phone in 30 minutes to stretch" (Hermes) | set_reminder with on_phone | first run: `"at": {"null": true}` was refused and Hermes asked for a time | **fail** |
| 29.5 (after fix) | same | same | 8.9 s, `on_phone: true`, "Your phone will also ring at that time" | pass |

**Needs your hands:** pair the phone in KDE Connect, then "find my phone", "send the clipboard to my phone", a file, and a phone reminder; optionally an ntfy topic for away from home.

## Phase 28: Screen understanding and daily news

Run on 2026-11-07 with real models and real feeds. The vision test captured a synthetic screen (an Excel window with a read-only error) instead of your real one, so nothing of yours reached the transcript; OCR, gemma3:4b, and the reload of Hermes were real.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 28.1 | `look_at_screen` "is anything wrong on the screen?" | the error, the right file name | 14.8 s cold: "Budget 2026.xlsx is showing as read-only ... save a copy" (gemma3 alone had read 2028) | pass |
| 28.2 | `look_at_screen` "what is the amount for groceries?" | 450 | 22.0 s: "the amount for groceries is 450" | pass, slow |
| 28.3 | `ollama ps` 25 s later | Hermes loaded, gemma3 gone | jarvis-hermes3 loaded, gemma3 unloaded | pass |
| 28.4 | `ai_news` with Groq | 8 stories, links, saved | first run: 8 stories in 3.5 s, but one OpenAI story twice (two feeds) and "Libghostty ... a Go library" made up from an empty Hacker News item | **fail** |
| 28.4 (after fix) | same | same | 2.7 s, no repeat, "Libghostty 1.0 was posted on Hacker News." | pass |
| 28.5 | `ai_news` with Hermes only | the same digest, slower | 15.7 s; first run had invented "a tool for generating fake comments"; after the fix "no details are available" | pass after fix |
| 28.6 | briefing line | the count | "8 AI and tech stories today; say "what's new in AI" to hear them." | pass |

**Needs your hands:** "what's on my screen" on your real screen, by voice.

## Phase 27: Music, developer tools, browser

Run on 2026-11-07 with `jarvis chat` and the real model through `scripts/drive_chat.py`, on a scratch data folder and config with a scratch repository `shop` (one changed file) and a local bare remote.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 27.1 | "what changed in my shop repo" | the branch, the file, the diff | `git_changes(shop)` in 0.2 s; "a change to cart.py on main ... adds a discount parameter" | pass |
| 27.2 | "commit it with a good message", y | a drafted message, asked, committed | `git_commit(message="Add discount feature to cart")`, asked, committed as 0a93899 | pass |
| 27.3 | "push it", y | asked with the count, pushed | asked, "Pushed main to origin."; the remote's log shows the commit | pass |
| 27.4 | benchmark: "open vs code at 9 tomorrow" | schedule_app | the model called `open_app` with `at`, which would have opened it at once | **fail**, fixed by ADR-095 (now refused, test added) |

**Needs your setup (not run):** Spotify with your keys (27.5), Docker Desktop running for `docker_up` (27.6), an SSH profile (27.7). The unit tests cover each with fakes: Spotify's API and media session, the Docker CLI, and the terminal command; git runs for real in a temporary repository.

## Phase 26: Apps, files, and office

Run on 2026-11-07 on the real desktop with a scratch data folder, config, and work folder (the only allowed folder), with Excel and Calculator closed beforehand: first tool calls without a model, then `jarvis chat` with the real model through `scripts/drive_chat.py`.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 26.1 | `open_app calculator` | opens, says how long | "Calculator is open, in 1.1 seconds." | pass |
| 26.2 | `calculator_show 18/100*2400`, `(1250+375)*3` | typed, read back, the same | "It's 432, and Calculator shows the same."; 4875, the same | pass |
| 26.3 | `schedule_app open calculator in 3 s` with the scheduler running | runs through the gate when due | "As you asked: Calculator is open, in 0.8 seconds." | pass |
| 26.4 | `take_note`, `read_notes` | saved and read back | "Noted."; "One note from today: the live test ran" | pass |
| 26.5 | add a row to a closed `.xlsx` | asked, written, backup kept | asked with the row shown; row 2 written; copy in `backups\sheets` | pass |
| 26.6 | add a row to a `.csv` made after the index was built | found and appended | first run: "No spreadsheet ... matches 'log'" | **fail** |
| 26.6 (after fix) | same | same | one rebuild, then `10:00;"tea; biscuits"` appended | pass |
| 26.7 | add a row to the workbook open in Excel | written in Excel, unsaved | first run: comtypes could not set `Cells(row, column)` (AttributeError, nothing written); second: Excel not yet in the running object table, so the locked file was refused | **fail** |
| 26.7 (after fix) | same | same | pywin32, found also through the workbook window; row 3 in Excel, workbook unsaved, file on disk unchanged; closed without saving | pass |
| 26.8 | chat: "note that the plumber comes on tuesday" | saved | first run: the model called take_note with `{"day": "tuesday"}`; now the template stage saves it in 6 ms without the model | pass after fix |
| 26.9 | chat: "add tea and 40 to my budget live sheet" | the row, after a yes | first run: the model passed `sheet = "live"`; a sheet name that is part of the file name is now ignored; row 2 written | pass after fix |
| 26.10 | chat: "close spotify in 20 minutes", "what's scheduled", "cancel the spotify one" | scheduled after a yes, listed, cancelled | first run: `at = "in 20 minutes"` refused, and the other two found no tools; after the fixes: "I'll close Spotify at 10:55 AM.", "One scheduled action: Close Spotify, 10:55 AM.", "Cancelled." | pass after fix |
| 26.11 | chat: "work out 12 times 7 in the calculator" | Calculator, 84 | `calculator_show 12*7`: "It's 84, and Calculator shows the same." | pass |

**Also found:** the new note phrases caught "add a note to call mom" in an MCP test; "make, take or add a note" now needs "that" or a colon. Read-back dates from Excel ("2026-11-07 00:00:00+00:00") are now said as dates. Not run: open_notes live (it would show your own Notepad tabs), a scheduled close that falls due while you are away, a real workbook of yours.

## Phase 25: Jarvis as an MCP server

Run on 2026-11-07 with `jarvis serve --no-voice --port 8799` on a scratch data folder and config (with `open_app`, `send_whatsapp`, and `read_file` added to `[mcp_server] tools` on purpose, and `confirm_timeout_s = 6`), driven by the MCP SDK's own stdio client starting `uv run jarvis mcp serve`, and a WebSocket client standing in for a UI.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 25.1 | `initialize`, `tools/list` | the listed public tools; never `send_whatsapp` or `read_file` | weather, calculate, convert_currency, market_data, crypto_price, web_search, open_app | pass |
| 25.2 | `calculate {"expression": "12 * 7"}` | 84, audited | `{"ok": true, "summary": "84", ...}` in 0.4 s; audit `auto`, `handled_by = mcp:...` | pass |
| 25.3 | `convert_currency` 100 USD to INR | a rate from the free API | "100 dollars is 9,392 rupees." in 0.1 s | pass |
| 25.4 | `send_whatsapp` called directly | refused by the running Jarvis | "Jarvis does not offer a tool called send_whatsapp.", no audit row | pass |
| 25.5 | `calculate {"nope": 1}` | invalid | "Invalid arguments for calculate: expression: Field required", audit `invalid` | pass |
| 25.6 | `open_app paint`, nobody answers | asked naming the client, then no | first run: the API saw the question as "Open Paint" without the client's name, and the refusal said "reply with exactly: Okay, I won't." | **fail** |
| 25.6 (after fix) | same | same | asked as "Claude Code wants to: Open Paint"; after 6 s: "The user did not answer in Jarvis in time, so it was not done." Paint did not open | pass |
| 25.7 | `open_app paint` from a client named Claude Code, answered no over the WebSocket | the question names the client; denied | "Claude Code wants to: Open Paint" (not in the allowlist); "The user said no in Jarvis..."; audit `denied`, `mcp:Claude Code` | pass |
| 25.8 | a call with `jarvis serve` stopped and a stale `bridge.json` | a clear sentence, no hang | "Jarvis is not running, so this tool cannot run..." in 2.2 s | pass |
| 25.9 | the log | each refused private name logged once per process | twice per start (send_whatsapp, read_file); the first run logged them on every call (fixed) | pass |

**Fixed in 25.6:** the question was renamed only for voice; the client's name now travels on the call (`ToolContext.requester`), so every channel and the audit see it, and a test covers the API's copy. Not run: a "yes" end to end (it would open Paint on this desktop; unit tests cover it), and a real Claude Code session (adding a server changes your Claude Code config, which is your call).

## Phase 24: Core on LangGraph and ChromaDB

Run on 2026-11-07 with `jarvis chat` through `scripts/drive_chat.py` on a scratch data folder and config, the real local model (jarvis-hermes3) and Groq.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 24.1 | start `jarvis chat` | the prompt at once, warm-up in the background | prompt shown; log "Warmed up in 2986 ms" a second later | pass |
| 24.2 | "open calculator" on a fresh data folder | the template stage gives up (index not built), the model opens it | "Router stage template took longer than 150 ms; skipped", then `open_app(Calculator)` by the model, `handled_by = agent` | pass |
| 24.3 | the router stages once the index exists ("open calculator", "open notepad", "volume 30", "mute", "open my report") | template matches for apps, volume, mute; none for a file | template `open_app` / `set_volume` in 0 to 3 ms; "open my report": no match. "open youtube" matched an installed YouTube app | pass |
| 24.4 | "what's 12 times 7" | "84", no model | "84" in 18 ms, `handled_by = arithmetic`, audit row `arithmetic` | pass |
| 24.5 | "remember that my manager is Ravi", then "who is my boss" | saved as a `user` memory, then found by meaning | `remember(about="user")`; "Your boss is Ravi." (no shared word, so through the vectors) | pass |
| 24.6 | data folder after 24.5 | a `chroma` folder, no network | `ld\Jarvis\chroma` created; ChromaDB tests fail any outside connection | pass |
| 24.7 | "compare the pros and cons of rust and go for a web backend" | the cloud answers, `handled_by = cloud` | gpt-oss-120b in 1.0 s, `handled_by = cloud` | pass |
| 24.8 | "explain in detail how public key cryptography works" | local: "key" and "crypto" touch local tool groups | answered locally in 32.6 s (unchanged rule from Phase 13, not this phase) | pass |
| 24.9 | `LLMClient.stream` on the real model: a question, then "please open Notepad for me" | text streams; the call arrives structured with nothing spoken | 49 text chunks, first after 1.4 s (warm); the call: 0 chunks spoken, `open_app {"name":"Notepad"}` | pass |
| 24.10 | Piper `speak_stream` with a silent player, three questions | first audio before the whole reply | 2.8 s vs 3.7 s, 3.6 s vs 5.0 s; a one-sentence reply: no gain | pass, smaller gain than hoped |
| 24.11 | stage times in history | `route_ms`, `llm_ms`, `first_tool_ms`, `tool_ms`, `turn_ms` | all present on every row | pass |

**Needs your hands:** a real voice turn with streaming on (24.10 was measured without playing sound), and "stop" while a streamed reply is playing.

## Phase 22: Remove the page and overlay

Run on 2026-11-05 with `jarvis serve --no-voice --port 8799` on scratch data, driven by a small client.

| # | Command | Expected | Actual | Result |
|---|---|---|---|---|
| 22.1 | read `bridge.json` | the port and a token | port 8799, a 32-character token | pass |
| 22.2 | `GET /health` | 200 with name and version only | `{"name": "jarvis", "version": "1.11.0"}` | pass |
| 22.3 | `GET /`, `/static/app.js`, `/docs` | 404: there is no page | 404, 404, 404 | pass |
| 22.4 | `GET /health` with `Origin: https://evil.example` | 403 | 403 | pass |
| 22.5 | `GET /health` with `Host: evil.example` | 400 | 400 | pass |
| 22.6 | WebSocket with no token, a wrong token, and the right token from a web page | all refused | all three refused at the handshake | pass |
| 22.7 | WebSocket with the token, then "what's 10 + 10" | hello, the events, "20" | `hello`; turn_started, tool_call_started, tool_call_finished, assistant_message, turn_finished; "20" (the first run added the morning briefing offer, which is right for the first command after 6 AM) | pass |
| 22.8 | `serve` after 22.7, with `speak_replies = true` | still running, the answer spoken | first run: **the process died** (exit 139, access violation) while loading Piper for the spoken answer | **fail** |
| 22.8 (after fix) | same | same | still answering `/health` 20 seconds later; the answer was spoken | pass |
| 22.9 | `jarvis serve --no-browser` (an old login shortcut) | starts | starts and prints the new banner | pass |
| 22.10 | `jarvis serve --help` | no browser flag, no overlay command | `--port`, `--no-voice`, `--wake`, `--model`, `--tray` only | pass |
| 22.11 | `jarvis chat` confirmations | y or n in the terminal | covered by 19.2, unchanged code | pass |

**Fixed in 22.8:** the winrt packages ship an old `msvcp140.dll`; loaded first, it made onnxruntime crash the process the first time Piper spoke. Not caused by this phase: voice mode never hit it only because the wake word loads onnxruntime first. `import jarvis` now loads Windows' own copy before anything else (R58), and `tests/unit/test_dll_order.py` fails without the fix.
