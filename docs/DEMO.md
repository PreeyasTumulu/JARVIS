# Demo script

A five-minute walk through what Jarvis does, in an order that tells a story: it runs locally, it acts on the laptop, it never acts on its own, and it reaches you when you are away. Record it with the Windows Snipping Tool (screen recording) or OBS, with system audio on so Jarvis's voice is in the video.

## Before recording

- `jarvis serve` running (the tray icon is blue), the page open in Brave next to a Notepad window.
- A test contact: `uv run jarvis contacts add "Demo" "+91 90000 00000" --alias friend` (a number that is yours or not real; the demo always answers "no" before anything is sent or called).
- Close anything private on screen: chats, notifications, files.
- Run `uv run jarvis voice --wake-test 10` once to check the microphone.

## Scenes

| # | Say | What the viewer sees | The point |
|---|---|---|---|
| 1 | "Hey Jarvis, what's the weather in Hyderabad?" | The tray turns red, then amber; the page logs `weather`; a one-sentence spoken answer | Voice, a real API, a short reply |
| 2 | "Open Notepad" then "type hello from Jarvis in Notepad" | Notepad opens and the text appears | It operates apps, not only answers |
| 3 | "Search YouTube for lofi music" | YouTube results open in Brave | Site searches in your own browser |
| 4 | "What's the share price of Reliance?" and "convert 100 dollars to rupees" | Two spoken answers with numbers from tools | Never guesses numbers |
| 5 | "Remember that my manager is Ravi" then "who is my manager?" | Saved, then answered from memory without a web search | Local memory |
| 6 | "Message friend that I will be late" | A Confirm card on the page and the spoken question; say "no" | Nothing is sent without your yes |
| 7 | "Call friend" | "Call Demo (number ending 0000) from your phone?"; say "no" | Phone Link calls, same rule |
| 8 | "Think harder: why did the Roman empire fall in the west but not in the east?" | The console names `openai/gpt-oss-120b`; a fast answer | A free cloud model for public questions only |
| 9 | "Think harder and explain what is on my clipboard" (copy a harmless sentence first) | Answered by `jarvis-hermes3` | Private content never leaves the laptop |
| 10 | In a terminal: `uv run jarvis claude-hook test` | Jarvis asks "Which color do you like? one, Blue..."; say "two"; the terminal prints `Green` | Claude Code's questions answered by voice |
| 11 | "Stop" during a long answer | Speech stops at once | Stop is deterministic |
| 12 | `uv run jarvis audit --last 12` | Every tool call with its decision | Everything is audited |

## Closing line

"Jarvis runs on this laptop, uses a local model by default, asks before anything that matters, and every action is in the audit log. The code, tests, and design decisions are on GitHub."
