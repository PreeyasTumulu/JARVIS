# Phase 1 model benchmark

Run on 2026-10-15 00:00, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 20 commands is sent once with the Jarvis system prompt and all Phase 1 tools. A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 100% (20/20) | 2.8 s | 4.0 s | 11.2 s | 61%/39% CPU/GPU | 0 |
| `jarvis-hermes3-3b` | 30% (6/20) | 0.8 s | 3.9 s | 6.4 s | 33%/67% CPU/GPU | 0 |
| `llama3.2:3b` | 85% (17/20) | 0.4 s | 0.6 s | 6.7 s | 20%/80% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 2.3 s |
| can you launch vs code | open_app | open_app | {"name":"vs code"} | 2.6 s |
| start docker | open_app | open_app | {"name":"docker"} | 2.6 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 2.8 s |
| bring up the calculator | open_app | open_app | {"name":"calculator"} | 2.7 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.6 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 3.1 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 3.5 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"reviews RTX 3050 laptop GPU"} | 4.0 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 3.4 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 3.8 s |
| say hello | speak | speak | {"text":"hello"} | 2.7 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 3.2 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 3.6 s |
| open the app | (no tool) or ask_user | (no tool) |  | 3.4 s |
| search for it | (no tool) or ask_user | (no tool) |  | 2.5 s |
| hi jarvis | (no tool) | (no tool) |  | 1.5 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 2.1 s |
| thanks, that's all | (no tool) | (no tool) |  | 2.4 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don't scientists trust atoms? Because they make | 4.2 s |

## `jarvis-hermes3-3b` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | **(no tool)** |  | 4.7 s |
| can you launch vs code | open_app | **(no tool)** |  | 0.6 s |
| start docker | open_app | **(no tool)** |  | 0.9 s |
| open whatsapp please | open_app | **(no tool)** |  | 0.5 s |
| bring up the calculator | open_app | **(no tool)** |  | 0.6 s |
| open chrome | open_app | **(no tool)** |  | 0.5 s |
| search the web for the latest python release | web_search | **(no tool)** |  | 0.7 s |
| who won the most recent cricket world cup | web_search | **(no tool)** |  | 0.6 s |
| find reviews of the RTX 3050 laptop GPU | web_search | **(no tool)** |  | 0.8 s |
| what is the latest news about OpenAI | web_search | **(no tool)** |  | 1.0 s |
| look up how tall the Burj Khalifa is | web_search | **(no tool)** |  | 0.5 s |
| say hello | speak | **(no tool)** |  | 0.5 s |
| read this out loud: the build passed | speak | **(no tool)** |  | 0.8 s |
| announce that the meeting starts in five minutes | speak | **(no tool)** |  | 1.6 s |
| open the app | (no tool) or ask_user | (no tool) |  | 0.6 s |
| search for it | (no tool) or ask_user | (no tool) |  | 0.6 s |
| hi jarvis | (no tool) | (no tool) |  | 2.1 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 0.9 s |
| thanks, that's all | (no tool) | (no tool) |  | 3.9 s |
| tell me a one line joke | (no tool) or speak | (no tool) |  | 1.1 s |

## `llama3.2:3b` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 0.4 s |
| can you launch vs code | open_app | open_app | {"name":"vs code"} | 0.3 s |
| start docker | open_app | open_app | {"name":"docker"} | 0.4 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 0.3 s |
| bring up the calculator | open_app | open_app | {"name":"calculator"} | 0.4 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 0.4 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 0.4 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 0.4 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"RTX 3050 laptop GPU reviews"} | 0.6 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"OpenAI latest news"} | 0.4 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"Burj Khalifa height"} | 0.4 s |
| say hello | speak | speak | {"text":"hello"} | 0.3 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 0.4 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting is about to start in five minutes, plea | 0.6 s |
| open the app | (no tool) or ask_user | **open_app** | {"name":"notepad"} | 0.4 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"search for it"} | 0.4 s |
| hi jarvis | (no tool) | **speak** | {"text":"Hi Jarvis, how can I assist you today?"} | 0.5 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 0.4 s |
| thanks, that's all | (no tool) | (no tool) |  | 0.1 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don"} | 0.3 s |
