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
