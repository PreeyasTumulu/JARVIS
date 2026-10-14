# Model benchmark (tool routing: all)

Run on 2026-10-15 00:56, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 30 commands is sent once with the Jarvis system prompt and all 16 tools. A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 80% (24/30) | 3.1 s | 4.2 s | 12.4 s | 61%/39% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 2.7 s |
| can you launch vs code | open_app | **focus_app** | {} | 2.3 s |
| start docker | open_app | **docker_list** | {"include_stopped":true} | 3.0 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 3.2 s |
| bring up the calculator | open_app | open_app | {"name":"calculator"} | 3.1 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.8 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 3.6 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 3.8 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"reviews RTX 3050 laptop GPU"} | 4.2 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 3.8 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 4.3 s |
| say hello | speak | speak | {"text":"hello"} | 2.7 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 3.6 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 3.9 s |
| open the app | (no tool) or ask_user | (no tool) |  | 1.9 s |
| search for it | (no tool) or ask_user | (no tool) |  | 3.4 s |
| hi jarvis | (no tool) | (no tool) |  | 1.6 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 2.2 s |
| thanks, that's all | (no tool) | (no tool) |  | 3.3 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don't scientists trust atoms? Because they make | 4.7 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 3.1 s |
| close the calculator | close_app | close_app | {"name":"calculator"} | 2.8 s |
| what docker containers are running | docker_list | docker_list | {} | 2.5 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 3.0 s |
| show me the logs of the backend container | docker_logs | **(no tool)** |  | 2.8 s |
| find my resume | find_file | **(no tool)** |  | 2.3 s |
| open the jarvis readme | find_file or open_file | **open_app** | {"name":"notepad"} | 3.2 s |
| what is this file | get_selected_file | **(no tool)** |  | 2.3 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 3.0 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"path":"jarvis project folder"} | 3.8 s |
