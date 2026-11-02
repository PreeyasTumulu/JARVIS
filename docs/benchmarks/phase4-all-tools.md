# Model benchmark (tool routing: all)

Run on 2026-10-15 09:14, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 45 commands is sent once with the Jarvis system prompt and all 31 tools. A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 67% (30/45) | 3.3 s | 4.4 s | 14.9 s | 58%/42% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 3.0 s |
| can you launch vs code | open_app | **focus_app** | {} | 2.9 s |
| start docker | open_app | **open_app** | {} | 2.6 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 3.5 s |
| bring up the calculator | open_app | **focus_app** | {"name":"calculator"} | 3.6 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 3.2 s |
| search the web for the latest python release | web_search | **(no tool)** |  | 3.5 s |
| who won the most recent cricket world cup | web_search | **(no tool)** |  | 3.9 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"RTX 3050 laptop GPU reviews"} | 4.8 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 4.1 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 4.7 s |
| say hello | speak | speak | {"text":"hello"} | 3.2 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 3.8 s |
| announce that the meeting starts in five minutes | speak | **(no tool)** |  | 4.3 s |
| open the app | (no tool) or ask_user | (no tool) |  | 2.9 s |
| search for it | (no tool) or ask_user | (no tool) |  | 2.8 s |
| hi jarvis | (no tool) | (no tool) |  | 1.9 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 4.2 s |
| thanks, that's all | (no tool) | (no tool) |  | 3.4 s |
| tell me a one line joke | (no tool) or speak | speak | {} | 2.8 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 3.4 s |
| close the calculator | close_app | close_app | {"name":"calculator"} | 3.1 s |
| what docker containers are running | docker_list | docker_list | {} | 2.7 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 3.3 s |
| show me the logs of the backend container | docker_logs | **(no tool)** |  | 3.3 s |
| find my resume | find_file | find_file | {"kind":"file","query":"resume"} | 4.0 s |
| open the jarvis readme | find_file or open_file | **open_app** | {} | 2.6 s |
| what is this file | get_selected_file | get_selected_file | {} | 3.0 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 3.2 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"path":"jarvis"} | 3.9 s |
| what's reliance trading at | market_data | **(no tool)** |  | 3.1 s |
| price of apple stock | market_data | **(no tool)** |  | 3.1 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 4.1 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"coin":"bitcoin","currency":"rupees"} | 4.5 s |
| convert 100 dollars to rupees | convert_currency | **(no tool)** |  | 5.2 s |
| what's the weather tomorrow | weather | **(no tool)** |  | 2.8 s |
| is it going to rain in mumbai today | weather | weather | {"day":"today","place":"Mumbai"} | 4.3 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 4.4 s |
| set the volume to 30 | set_volume | **(no tool)** |  | 3.0 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 3.2 s |
| lock my laptop | lock_screen | **(no tool)** |  | 2.0 s |
| take a screenshot | screenshot | screenshot | {} | 2.4 s |
| what did I copy | clipboard_read | clipboard_read | {} | 2.8 s |
| set a timer for 5 minutes | set_timer | set_timer | {"minutes":5} | 3.4 s |
| remind me in 10 minutes to stretch | set_reminder | **(no tool)** |  | 3.4 s |
