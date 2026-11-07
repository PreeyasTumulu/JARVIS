# Research: other Jarvis projects, phone calls, and what to build next

Sections 1 to 5 were written during Phase 9 (2026-10-20): what similar open-source assistants do, how Jarvis can make and take phone calls, how to keep the model small but smart, and which features are worth building next. Section 6 (Phase 23, 2026-11-05) surveys the wider field again before the core moves to LangGraph, with the full report in [research/open-source-assistants-2026.md](research/open-source-assistants-2026.md). Sources are linked where they are used.

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
| WhatsApp desktop call | free | built, the default since Phase 17 (ADR-069) |
| Twilio "click to call" (Twilio rings you, then connects your mom) | about 5 US cents a minute to Indian mobiles (2026-11-07, [Twilio India pricing](https://www.twilio.com/en-us/voice/pricing/in)) | not built; Phone Link covers it for free (section 2.4) |

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

### 2.4 Phase 29: calls where Jarvis speaks, and the free alternative (2026-11-07)

Asked before building anything: what a call that Jarvis speaks in would cost from India, what number it would come from, and what the law allows.

**Cost (Twilio's own India page).** $0.0496 a minute to an Indian mobile and $0.0699 to a landline (about Rs 4 to 5 and Rs 6); a US number from $1.15 a month (about Rs 100). A trial account only calls up to 5 verified numbers, plays a trial notice first, and ends after 30 days.

**Numbers.** Twilio says calls into India can only come from non-Indian numbers, and Indian carriers must label calls from abroad "International call". Showing your own Indian number as the caller ID would not help: since 22 October 2024 DoT blocks calls from abroad that carry an Indian number as spoofed. Plivo (Rs 0.38 a minute, Rs 200 a month) and Exotel sell Indian numbers only to businesses registered in India (GST, incorporation, or Udyam papers).

**Law.**

| Rule | What it means here |
|---|---|
| TRAI TCCCPR 2018, amended February 2025 (promotional calls from the 140 series, service calls from 1600, fines Rs 2 to 10 lakh) | covers commercial calls; personal calls to people who expect them are outside it |
| Twilio's India guidance | consent needed or the calls count as unsolicited and can be blocked; many short calls trip carrier blocks; no voice OTPs; no emergency numbers |
| DPDP Act 2023, section 3 | does not apply to an individual's personal or domestic use |
| Recording a call you are part of | no Indian statute found; a spoken notice before recording is the safe course |
| AI disclosure | not required for personal calls; TRAI has only a draft for commercial AI calls |

**Free ways to reach your phone instead.**

| Way | Where | What it can do | Privacy |
|---|---|---|---|
| **KDE Connect** (installed, phone visible) | same Wi-Fi | ring loudly even on silent, notify, send files, links, text, the clipboard, SMS from your SIM | never leaves your network |
| **ntfy** (built into the bridge since Phase 9) | anywhere | urgent push, up to three answer buttons; the app can keep alerting and override Do Not Disturb if you allow it | through ntfy.sh unless self-hosted |
| Telegram bot | anywhere | messages, files up to 50 MB, buttons, commands from the phone | through Telegram's servers |
| Phone Link | Bluetooth | dials from your SIM for free | Jarvis cannot speak into the call without a virtual audio cable |

You chose KDE Connect with ntfy, and WhatsApp for messages to people (ADR-098, ADR-099).

Sources: [Twilio India voice pricing](https://www.twilio.com/en-us/voice/pricing/in), [Twilio India voice guidelines](https://www.twilio.com/en-us/guidelines/in/voice), [Twilio trials](https://www.twilio.com/docs/usage/trials), [Plivo India pricing](https://www.plivo.com/voice/pricing/in/), [Plivo India numbers](https://docs.plivo.com/docs/numbers/rent-india-numbers), [TRAI press release 11 of 2025](https://cms.trai.gov.in/sites/default/files/2025-02/PR_No.11of2025.pdf), [JSA on the 2025 amendments](https://www.jsalaw.com/wp-content/uploads/2025/02/JSA-Prism-Telecommunications_February-2025_TCCCPR-amendments.Final_.pdf), [ThePrint on the spoofed-call system](https://theprint.in/india/dot-tsps-deploy-new-system-to-block-spoofed-international-calls/2298121), [DPDP Act section 3](https://dpdpa.com/dpdpa2023/chapter-1/section3.html), [Exotel on call recording](https://exotel.com/glossary/call-recording-compliance-in-india/), [ntfy keep alerting](https://github.com/binwiederhier/ntfy/issues/417). This is research, not legal advice.

## 3. Small but smart

The laptop has an RTX 3050 with 4 GB and 16 GB of RAM. Hermes 3 8B runs 58% on the CPU, which is why a turn takes 2 to 4 seconds. Ways to get more out of it, roughly in order of value (Phase 13 measured the first five; see ADR-061 to ADR-063):

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
| 8 | Focus sessions (built in Phase 20) | mute notifications, start a timer, say the summary after | small |
| 9 | Clipboard history and "paste the second last thing I copied" (built in Phase 20) | handy, privacy-sensitive | small |
| 10 | A fast intent model | lower latency and better routing | medium |
| 11 | Barge-in with echo cancellation | interrupt Jarvis by voice, not only the hotkey | medium, hardware dependent |
| 12 | Multi-language speech (Hindi, Telugu) | Whisper `small` (not `.en`) and a Piper voice per language | medium |

## 5. Making it a showcase open-source product

Done in Phase 9: CI with lint, format, types, tests, the scripted end-to-end suite, coverage with a floor, a dash check; a troubleshooting guide; a demo script; contributing and security guides; architecture and decision records for every choice.

Still worth doing once you sign off: a short demo video (the script is in [DEMO.md](DEMO.md)), a GitHub release with a changelog per phase, issue and pull request templates, screenshots of the web page and tray in the README, and a `CODEOWNERS` file. A one-command installer (`install.ps1` that checks for uv and Ollama and pulls the model) would lower the barrier for others.

## 6. The wider field in November 2026 (Phase 23)

Five research passes over the projects your brief named, plus the strongest "JARVIS"-style repos, then a synthesis with every claim linked. The full report, with about 120 sources, is [research/open-source-assistants-2026.md](research/open-source-assistants-2026.md). Four claims that Phase 24 builds on were re-checked by hand against the primary source (marked "checked" below).

### 6.1 What each one is now

| Project | Architecture and tools | Safety | UI and voice | Users like / dislike | Status |
|---|---|---|---|---|---|
| [Open Interpreter](https://github.com/openinterpreter/open-interpreter) | Now a Rust fork of OpenAI Codex with a native sandbox, approvals, MCP, skills; the classic Python "run any code" design lives on in an AGPL fork | classic `safe_mode` is off by default and "experimental" | terminal; the 01 voice device is still experimental | like: power; dislike: arbitrary code execution, the rename | 0.0.59, 2026-11-04 |
| [Leon](https://github.com/leon-ai/leon) | 2.0 rewrite: one TypeScript server, agent / smart / controlled (deterministic) modes, ReAct loop with runtime argument guards, tool schemas loaded in stages, tools in isolated workers, `SKILL.md` skills | tools the owner disables, limits, clarification pauses; no code gate | web app | like: the memory design; dislike: install pain, one maintainer | 2.0 developer preview only |
| [OpenVoiceOS](https://openvoiceos.github.io/ovos-technical-manual/) | services on a local message bus; an ordered, confidence-tiered `intents.pipeline` with the LLM ("persona") only as a fallback | network limits, speaker verification at wake; no permission model | GUI state server, drawn by separate clients | like: privacy, offline; dislike: many install paths, no Windows | 3.7.x alpha line |
| [Home Assistant Assist](https://www.home-assistant.io/voice_control/) | "prefer handling commands locally" by default: templates first, LLM only for the rest, one shared conversation; intents become LLM tools; MCP server and client | which devices are exposed is the main guard; no confirm or PIN step for an LLM unlock was found | Voice PE LED ring, Assist dialog; streaming TTS took first audio from 5.31 s to 0.56 s | like: local control; dislike: wake word misses, small LLMs toggling the wrong device | 2026.11.0, 2026-11-04 |
| [Willow](https://heywillow.io/) | ESP32-S3 box streams to a GPU Whisper server, then to any REST endpoint | none of its own | the box's display | like: speed (500 ms is a vendor claim); dislike: fixed on-device grammar | fixes only, one maintainer |
| [Pipecat](https://github.com/pipecat-ai/pipecat) | a pipeline of frame processors with a local audio transport; Smart Turn end-of-turn model on CPU; tools with `cancel_on_interruption`, `timeout_secs`, progress results (checked) | no built-in human in the loop | RTVI events, voice UI kit | like: flexible, local; dislike: breaking releases, no Windows docs | v1.15.0, late Oct |
| [LiveKit Agents](https://github.com/livekit/agents) | workers and `AgentSession` over WebRTC rooms; turn detector, interruption handling with false-interruption recovery, `max_tool_steps`, SIP calls | no built-in human in the loop | agent states `initializing`, `idle`, `listening`, `thinking`, `speaking` and user states `speaking`, `listening`, `away` (checked) | like: telephony, polish; dislike: a room server for a desktop app | 1.8.10, late Oct |
| [Open WebUI](https://github.com/open-webui/open-webui) | web chat over Ollama; Tools and Functions run Python in the server process; MCP and OpenAPI tool servers | per-call approval is "experimental and off by default" (checked); ten advisories in five weeks of 2026 | sentence-by-sentence voice mode | like: features; dislike: the non-OSI licence since v0.6.6, security | v0.13.0, early Nov |
| [OpenClaw](https://github.com/openclaw/openclaw), [Hermes Agent](https://github.com/NousResearch/hermes-agent) | the two giant personal-agent platforms of 2026, chat-app first, skills and MCP (Hermes) | tools run on the host unless sandboxing is set up; a malware skill on ClawHub | chat apps, not voice | like: reach; dislike: security | very active |
| [Microsoft UFO2](https://github.com/microsoft/UFO), [Windows-MCP](https://github.com/CursorTouch/Windows-MCP) | the Windows references: explicit agent state machines, an app's own API first and UI Automation second, vision last | UFO2 works in a nested desktop; Windows-MCP calls its rules "not server-enforced" | none | like: Windows depth; dislike: cursor fights (Windows-MCP) | active |
| [isair/jarvis](https://github.com/isair/jarvis) | voice-first desktop assistant, a separate fast routing model, MCP, a diary and graph memory | none in the voice path | floating face, tray, "pause listening, keep typing", a task centre | dislike: the same Windows model-load and freeze failures Jarvis lists in RISKS.md | active, personal-use licence |

**The field agrees on the shape and disagrees on safety.** The mature projects route obvious commands without a model, stream speech, and extend through MCP and `SKILL.md` files. Almost none of them enforces confirmation in code. Small local models are the shared weak point: Open WebUI's docs say models "under ~30B parameters often produce malformed JSON" in tool calls (checked).

### 6.2 What we are taking

Each one becomes a task in the phase named.

| From | Pattern | Becomes, in Jarvis | Phase |
|---|---|---|---|
| OpenVoiceOS, Home Assistant | an ordered, tiered pipeline in config, every stage time-bound | `router.pipeline = [exact_phrase, arithmetic, template, agent]`, each stage answering match or none within a time limit | 24 |
| Home Assistant | one executor and one conversation for both paths | fast-path hits written into the LangGraph state as tool calls, through the same gate; a test fails if any fast path calls a tool function directly | 24 |
| Home Assistant `processed_locally` (checked) | which path handled the turn | a `handled_by` field on every turn and audit row, so fast-path coverage is a number | 24 |
| Home Assistant templates | runtime templates with slots, an intent cache | "open {app}", "volume {percent}" filled from the registry at runtime | 24, 26 |
| Leon | tool schemas loaded in stages; runtime guards that repair arguments and drop duplicate calls | a guard node before the gate: schema check, one repair try, no repeated call, a step cap; toolkit summaries first for Hermes | 24 |
| Microsoft UFO2 | named agent states | graph nodes route, guard, gate, await_confirmation, execute, respond, each mapped to a UI state | 24 |
| Microsoft UFO2 | the app's own API first, UI Automation second | apps, Excel, and Calculator tools use COM or a CLI before clicks, and the audit log says which | 26 |
| Home Assistant tool annotations | assume the worst for unknown tools | every MCP tool starts at `confirm` and `private`; a server's own annotations can only tighten that; names `mcp__server__tool` so none shadows a built-in | 25 |
| Pipecat (checked) | `cancel_on_interruption`, `timeout_secs`, progress results | tool options for long tools (Docker, downloads, calls): "stop" reaches them, and they can say how far they are | 24, 27 |
| Leon, Hermes | `SKILL.md` workflows | skills as files that may only call registered tools, so the gate sees every step | 25 |
| Home Assistant, Open WebUI | streaming TTS by sentence | Piper starts on the first sentence of the model's reply; measured against Home Assistant's 0.56 s | 24 |
| Pipecat | per-stage latency breakdown | VAD, STT, first token, first audio, and tool time for every turn, in the audit log and benchmarks | 24 |
| LiveKit (checked) | the agent and user state vocabulary | the event contract the new UI binds to, plus `awaiting_confirmation`, `running_tool`, `paused`, `error` | 24, 30 |
| LiveKit | false-interruption recovery; store only what was spoken | for barge-in later; the stored reply is cut to what was actually played | later |
| Home Assistant | a chime instead of "Done" | for fast actions with a visible effect | 30 |
| isair/jarvis | pause listening, keep typing; a task list | the new UI's mic switch and background-task view | 30 |
| Open WebUI | memory types with character budgets | `user` and `context` memories with budgets sized for an 8B context | 24 |
| Leon | memory work after the turn | ChromaDB writes after speech has started, never on the reply path | 24 |

### 6.3 Where we do better, and keep doing better

1. **Confirmation on by default, in code.** Every surveyed system makes approval opt-in, leaves it to "guidelines", or has none in the voice path. Jarvis's risk floors stay a documented contract with tests: no config, MCP annotation, or skill can lower one.
2. **Privacy labels that travel.** No surveyed project routes by sensitivity. In Phase 24 the label moves with every tool result and memory record through the graph state, and any cloud-bound call whose inputs hold a private value is blocked.
3. **Taint per turn.** After a turn has read untrusted content (a page, file, clipboard, or MCP result), its remaining acting tools need a confirm, an idea from ethanplusai/jarvis made into a tightening rule.
4. **Every entry point through the gate.** Open WebUI's CVE-2026-45395 came from one update path that skipped a permission check. Phase 24 adds a test that lists every way a tool can be registered, updated, or called and checks each one meets the gate.
5. **No third-party code in the Jarvis process.** Open WebUI's in-process tools and ClawHub's malware skill show the cost. Outside capabilities stay MCP subprocesses with a scrubbed environment, and adding one is off until you turn it on.
6. **Measured, not assumed.** None of the projects publishes a malformed-tool-call rate or per-stage latency on real hardware. Jarvis logs both for Hermes 3 8B on the RTX 3050 and publishes them per release.
7. **Windows first, failures named.** Most of the field is macOS or Linux first. Jarvis keeps naming its Windows gaps in RISKS.md: no echo cancellation on laptop speakers, wake word false accepts, and UI Automation competing with your cursor.

### 6.4 Licences

- **Piper:** the installed `piper-tts` 1.8.0 is **GPL-3.0-or-later** (checked in its package metadata; it comes from `OHF-Voice/piper1-gpl`), while Jarvis is MIT. This matches [ADR-006](DECISIONS.md#adr-006-mit-license-piper-as-an-optional-extra): Piper stays an optional extra that Jarvis never bundles. The Phase 31 installer must keep it that way, or switch the default voice to an Apache-2.0 engine such as Kokoro.
- Code is not copied from Open WebUI after v0.6.5 (non-OSI licence), classic Open Interpreter or 01 (AGPL-3.0), or isair/jarvis (personal use only). Ideas are taken, not code.
- LiveKit's turn-detector models have their own model licence, and Smart Turn's model licence is not stated in its docs; either is checked before use.
