# Research: other Jarvis projects, phone calls, and what to build next

Written during Phase 9 (2026-10-20). It answers four questions: what similar open-source assistants do, how Jarvis can make and take phone calls, how to keep the model small but smart, and which features are worth building next. Sources are linked where they are used.

## 1. Similar open-source projects

| | Jarvis (this repo) | [isair/jarvis](https://github.com/isair/jarvis) | [PanPenek/JarvisAi](https://github.com/PanPenek/JarvisAi) |
|---|---|---|---|
| Platform | Windows 11, deep integration | macOS first; Windows and Linux supported | Windows |
| Wake | openWakeWord "Hey Jarvis", push-to-talk | its name anywhere in a sentence, from a rolling transcript | openWakeWord "Hey Jarvis" |
| Speech | faster-whisper, Piper or SAPI | faster-whisper, Piper (Chatterbox optional) | faster-whisper, Kokoro-82M |
| Model | Hermes 3 8B on Ollama; free cloud (Groq, OpenRouter) for public questions only | Gemma 4 E2B or E4B by default, Qwen options; a separate fast model for intent and routing | Qwen3 8B, LM Studio, or any OpenAI-compatible API |
| Tools | 46 typed tools with risk levels, a policy gate, and an audit log | built-ins plus MCP servers (Home Assistant, GitHub, browsers, databases) | 31 tools, OCR screen reading and clicking by coordinates, up to 15 chained calls |
| Memory | stated facts, local only | a diary and a knowledge graph, with a viewer | SQLite plus ChromaDB semantic search, auto-summarized context |
| Safety | confirmations bound to the exact action, allowlists, egress rule, privacy router, secret redaction | redaction before context and diary | sandboxed file paths and Python |
| Unique | WhatsApp, notifications, Phone Link calls, the Claude Code bridge, Brave automation | dictation that pastes into any app, a task queue, low-power mode | OCR vision, `run_python`, sub-agent delegation |

What is worth borrowing:

1. **A small, fast intent model** next to the main model (isair). A 0.5B to 1.5B model, or plain rules, picks the tool group in about 100 ms, so the 8B model only sees the few tools that matter. Jarvis's keyword routing already does a rule-based version; a learned one would cover paraphrases.
2. **MCP client support** (isair). One integration point gives Home Assistant, GitHub, calendars, and databases, each server with its own tools. Each MCP tool would get a risk floor and a sensitivity label like any other Jarvis tool, defaulting to `confirm` and `private`.
3. **Dictation** (isair). Hold a hotkey, speak, and the text is pasted where the cursor is. Jarvis already has Whisper, a hotkey listener, and SendInput, so this is small.
4. **Screen reading with OCR** (PanPenek) as a fallback where UI Automation sees nothing (games, some Electron apps, images). Windows has a built-in OCR engine (`Windows.Media.Ocr`) reachable through pywinrt, which Jarvis already uses for notifications.
5. **Semantic memory and summaries** (PanPenek). `nomic-embed-text` is already pulled on this laptop; memories and past turns could be found by meaning, not shared words.
6. **Name-anywhere addressing** (isair): "set a timer, Jarvis, for ten minutes". Needs a rolling transcript, which means always transcribing; more privacy cost than the wake word.

## 2. Phone calls

There are three different things here, with different answers.

### "Call my mom" (you talk to someone)

| Way | Cost | Status |
|---|---|---|
| **Phone Link** (`tel:` link, your Android phone dials over Bluetooth, you talk through the PC) | free | built: `call_contact`, asks first, needs your test (ADR-053) |
| WhatsApp desktop call | free | possible through UI Automation (open the chat, press the call button); brittle, not built |
| Twilio "click to call" (Twilio rings you, then connects your mom) | about 1 to 3 US cents a minute to Indian mobiles ([Twilio India pricing](https://www.twilio.com/en-us/voice/pricing/in)) | not built; Phone Link covers it for free |

### "Jarvis, call me" (Jarvis reaches you when you are away from the laptop)

| Way | What you get | Cost |
|---|---|---|
| **ntfy push** ([ntfy.sh](https://ntfy.sh), open source, self-hostable) | an urgent notification that rings like an alarm, with up to three answer buttons | free |
| **Twilio voice call** | your phone actually rings; Jarvis says the question; you press a key or speak | paid per minute; trial accounts call verified numbers only |
| Telegram bot | a chat message with buttons, voice notes | free; no real calls |

Both ntfy and Twilio are built into the bridge (ADR-052) and off until you choose one.

### "When Claude needs me, Jarvis asks me" (the Claude Code bridge)

Built (ADR-051). Claude Code's hooks hand Jarvis every multiple-choice question (`AskUserQuestion`) and every permission prompt. Jarvis says it aloud with numbered options and shows it on the page, you answer "two" (or click), and the answer goes back to Claude as if you had picked it in the terminal. The hook format is from the official docs ([code.claude.com/docs/en/hooks](https://code.claude.com/docs/en/hooks)): `permissionDecision: "allow"` plus `updatedInput.answers` answers a question, and `decision.behavior` allows or denies a permission. If you are not at the PC, the question can follow you to your phone (ntfy or Twilio) after `escalate_after_s`.

The flow in one line: Claude asks, the hook posts to Jarvis on 127.0.0.1, Jarvis asks you by voice, page, or phone, your answer is matched to an option without any model, and the hook prints Claude's answer.

## 3. Small but smart

The laptop has an RTX 3050 with 4 GB and 16 GB of RAM. Hermes 3 8B runs 58% on the CPU, which is why a turn takes 2 to 4 seconds. Ways to get more out of it, roughly in order of value:

1. **Ollama speed settings** (needs your OK, ADR open decision 3): `OLLAMA_FLASH_ATTENTION=1` and `OLLAMA_KV_CACHE_TYPE=q8_0` halve the context memory, so more of the model fits on the GPU.
2. **A 4B tool-calling model as the default**: Qwen3 4B or Gemma 3n/Gemma 4 E4B class models fit entirely in 4 GB at Q4 and are often as good at single tool calls. `scripts/benchmark_tools.py --models ...` compares them on Jarvis's own 67 commands; `gemma3:4b` and `llama3.2:3b` are already pulled.
3. **Fewer tools per request**: every tool schema costs prompt tokens and accuracy. Keyword routing already narrows 46 tools to 5 to 10; a fast intent model (section 1) would do better.
4. **Deterministic fast paths**: "stop", yes or no, volume, timers, and "search YouTube for X" can be parsed without any model, which is instant and cannot be fooled.
5. **Whisper on the GPU or a smaller Whisper**: `small.en` on 8 CPU threads takes 1.6 s for a short command; `base.en` is about three times faster with a little more error, and `distil-small.en` sits in between.
6. **The cloud for hard public questions only** (built): Groq answers in under a second when you say "think harder", and nothing private is ever sent.

## 4. Features worth building next

Ranked by value for daily use against effort. Each would come with its own decisions, tests, and risk notes.

| # | Feature | Why | Effort |
|---|---|---|---|
| 1 | Dictation into any app | the most used voice feature in daily work | small |
| 2 | Calendar and email (Google or Outlook) read, then draft with confirmation | "what's on today", "reply that I'm running late" | medium; needs OAuth decisions |
| 3 | MCP client | Home Assistant, GitHub, databases without writing each tool | medium |
| 4 | Morning briefing | weather, calendar, unread WhatsApp count, reminders, Claude sessions waiting | small once 2 exists |
| 5 | Windows OCR fallback for apps UI Automation cannot read | covers the gaps in screen reading | small |
| 6 | Semantic memory with `nomic-embed-text` | memories found by meaning; "what did I ask about Docker last week" | medium |
| 7 | Media control (play, pause, next) through the system media keys | "pause the music" without knowing the app | small |
| 8 | Focus sessions | mute notifications, start a timer, say the summary after | small |
| 9 | Clipboard history and "paste the second last thing I copied" | handy, privacy-sensitive | small |
| 10 | A fast intent model | lower latency and better routing | medium |
| 11 | Barge-in with echo cancellation | interrupt Jarvis by voice, not only the hotkey | medium, hardware dependent |
| 12 | Multi-language speech (Hindi, Telugu) | Whisper `small` (not `.en`) and a Piper voice per language | medium |

## 5. Making it a showcase open-source product

Done in Phase 9: CI with lint, format, types, tests, the scripted end-to-end suite, coverage with a floor, a dash check; a troubleshooting guide; a demo script; contributing and security guides; architecture and decision records for every choice.

Still worth doing once you sign off: a short demo video (the script is in [DEMO.md](DEMO.md)), a GitHub release with a changelog per phase, issue and pull request templates, screenshots of the web page and tray in the README, and a `CODEOWNERS` file. A one-command installer (`install.ps1` that checks for uv and Ollama and pulls the model) would lower the barrier for others.
