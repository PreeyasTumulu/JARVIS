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
