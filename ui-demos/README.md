# UI demos

Six standalone concepts for how Jarvis could look, built in Phase 30 (ADR-100), and the chat interface made from the two you chose (ADR-101). Each is one HTML file. Double-click it, or run `python -m http.server 8780 --directory ui-demos` and open http://127.0.0.1:8780. Nothing connects to Jarvis yet: each page plays a short scripted run with real lines from Jarvis. You hear "send the clipboard to my phone", Jarvis asks first, sends it, and then cannot find a phone that is not paired.

On any page:
- **State buttons, or keys `1` to `7`:** show one state. This pauses the run.
- **Space**, or "Play the demo": plays the run again.
- **"Use my microphone":** listening follows your real voice level. Only a loudness number is read; the sound is not recorded and never leaves the page.

The pages make no network requests: no web fonts, no scripts from elsewhere. A test checks this. They use fonts Windows 11 already has (Bahnschrift, Segoe UI Variable, Sitka, Consolas). Movement stops when Windows has animations turned off (reduced motion).

## The chat (the chosen direction)

Since Phase 32 this page is also the real Jarvis window: `jarvis serve` serves it, and `jarvis ui` opens it, live (ADR-103). Opened from disk, as here, it plays the demo.

`chat.html` brings the orb and the edge glow together around a conversation.
- **The orb:** waits large in the middle, then glides up into the header once you talk. New chat sends it back.
- **The edge glow:** the window's edge glows in the orb's colour for each state.
- **Your words:** appear in your bubble as you speak, and Jarvis's reply appears word by word while it is spoken.
- **Confirmations:** a card in the conversation.
- **Talking and typing:** type and press Enter, or press the mic. Stop interrupts. Try "send the clipboard to my phone", "find my phone", or "set a timer".
- **Themes:** light and dark follow Windows, and the moon or sun button switches them.

| Waiting for your yes | Speaking | Listening | Thinking |
|---|---|---|---|
| ![](screenshots/chat-confirm.jpg) | ![](screenshots/chat-speaking.jpg) | ![](screenshots/chat-listening.jpg) | ![](screenshots/chat-thinking.jpg) |

## The states

Every demo shows the same seven states. They are the `AgentStateChanged` and voice events the real UI will bind to (ARCHITECTURE.md 4.1).

| State | When |
|---|---|
| Idle | waiting for "Hey Jarvis" |
| Listening | you are speaking; your words appear as they are heard |
| Thinking | the model is choosing what to do |
| Speaking | Jarvis answers |
| Waiting for your yes | a tool that needs a confirmation, with Yes and No |
| Running a tool | the tool's name while it runs |
| Error | what went wrong and how to fix it |

## The six concepts

**Reactor** (`reactor.html`). Steel rings, a turning aperture, and one warm core on deep blue. The ticks lift with your voice, a lit arc sweeps while thinking, and the rings step round while a tool runs. The film-like one.

| Listening | Thinking | Waiting for your yes | Speaking |
|---|---|---|---|
| ![](screenshots/reactor-listening.jpg) | ![](screenshots/reactor-thinking.jpg) | ![](screenshots/reactor-confirm.jpg) | ![](screenshots/reactor-speaking.jpg) |

**Orb** (`orb.html`). A soft shape in daylight that changes colour per state, grows with your voice, and shakes once on an error. The words are set large in Sitka. The calm one.

| Listening | Thinking | Waiting for your yes | Speaking |
|---|---|---|---|
| ![](screenshots/orb-listening.jpg) | ![](screenshots/orb-thinking.jpg) | ![](screenshots/orb-confirm.jpg) | ![](screenshots/orb-speaking.jpg) |

**Edge glow** (`edge.html`). The screen's edge lights up: it widens with your voice and turns while Jarvis thinks. One small caption sits above the taskbar, so your work stays in view.

| Listening | Thinking | Waiting for your yes | Speaking |
|---|---|---|---|
| ![](screenshots/edge-listening.jpg) | ![](screenshots/edge-thinking.jpg) | ![](screenshots/edge-confirm.jpg) | ![](screenshots/edge-speaking.jpg) |

**Terminal** (`terminal.html`). `jarvis chat` as the whole interface, in peach on plum. Every state is a line you can read back, the confirmation takes `y` or `n`, and a status bar shows the state and the level.

| Listening | Thinking | Waiting for your yes | Speaking |
|---|---|---|---|
| ![](screenshots/terminal-listening.jpg) | ![](screenshots/terminal-thinking.jpg) | ![](screenshots/terminal-confirm.jpg) | ![](screenshots/terminal-speaking.jpg) |

**Pill** (`pill.html`). A small dark capsule above the taskbar that grows only as much as each state needs. It is a dash when idle, holds a waveform and your words while listening, and opens to two lines for a yes. The practical one.

| Listening | Thinking | Waiting for your yes | Speaking |
|---|---|---|---|
| ![](screenshots/pill-listening.jpg) | ![](screenshots/pill-thinking.jpg) | ![](screenshots/pill-confirm.jpg) | ![](screenshots/pill-speaking.jpg) |

**Constellation** (`constellation.html`). A globe of 240 stars. It leans out with your voice, spins with trails while thinking, ripples while speaking, and gathers into a ring while it waits for your yes.

| Listening | Thinking | Waiting for your yes | Speaking |
|---|---|---|---|
| ![](screenshots/constellation-listening.jpg) | ![](screenshots/constellation-thinking.jpg) | ![](screenshots/constellation-confirm.jpg) | ![](screenshots/constellation-speaking.jpg) |

## Changing them

- **The kit:** the states, the scripted run, the controls and the microphone live once, in `_kit.js`. Each page carries a copy between its `// kit:begin` and `// kit:end` markers, so it stays one file. After editing the kit, run `uv run python scripts/build_ui_demos.py`. `tests/unit/test_ui_demos.py` fails while a copy is out of date.
- **Screenshots:** `uv run python scripts/capture_ui_demos.py` opens each page with `?state=<name>&still`, which freezes one frame, and saves the images here. Add `--all` for every state, or `--width 390 --height 844` for a phone.
