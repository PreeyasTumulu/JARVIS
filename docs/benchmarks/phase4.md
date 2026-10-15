# Model benchmark (tool routing: keywords)

Run on 2026-10-15 09:19, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 45 commands is sent once with the Jarvis system prompt and the tools keyword routing selects (all of them when nothing matches). A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 89% (40/45) | 2.6 s | 3.6 s | 14.8 s | 58%/42% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 2.1 s |
| can you launch vs code | open_app | **focus_app** | {} | 2.1 s |
| start docker | open_app | **docker_list** | {"include_stopped":true} | 2.5 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 2.0 s |
| bring up the calculator | open_app | **(no tool)** |  | 1.7 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.2 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 2.4 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 2.4 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"RTX 3050 laptop GPU reviews"} | 4.4 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 3.3 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 3.6 s |
| say hello | speak | speak | {"text":"hello"} | 2.1 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 2.7 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 2.7 s |
| open the app | (no tool) or ask_user | (no tool) |  | 2.9 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"python function search"} | 2.8 s |
| hi jarvis | (no tool) | (no tool) |  | 1.9 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 4.1 s |
| thanks, that's all | (no tool) | (no tool) |  | 3.6 s |
| tell me a one line joke | (no tool) or speak | speak | {} | 2.9 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 2.9 s |
| close the calculator | close_app | **(no tool)** |  | 2.1 s |
| what docker containers are running | docker_list | docker_list | {"include_stopped":true} | 2.6 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 2.2 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend","lines":10} | 3.3 s |
| find my resume | find_file | find_file | {"kind":"file","query":"resume"} | 3.2 s |
| open the jarvis readme | find_file or open_file | find_file | {"kind":"file","query":"readme"} | 3.5 s |
| what is this file | get_selected_file | get_selected_file | {} | 2.4 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 2.5 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"line":null,"path":"jarvis project folder"} | 2.8 s |
| what's reliance trading at | market_data | market_data | {"query":"Reliance"} | 2.6 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 2.2 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 2.9 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"coin":"bitcoin","currency":"rupees"} | 3.5 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"amount":100,"from_currency":"dollars","to_currency":"rupee | 4.4 s |
| what's the weather tomorrow | weather | weather | {"place":null,"day":"tomorrow"} | 2.6 s |
| is it going to rain in mumbai today | weather | weather | {"day":"today","place":"Mumbai"} | 2.9 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 2.9 s |
| set the volume to 30 | set_volume | set_volume | {"level":30} | 2.6 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 2.3 s |
| lock my laptop | lock_screen | lock_screen | {} | 2.0 s |
| take a screenshot | screenshot | screenshot | {} | 2.0 s |
| what did I copy | clipboard_read | clipboard_read | {} | 2.2 s |
| set a timer for 5 minutes | set_timer | set_timer | {"minutes":5} | 2.7 s |
| remind me in 10 minutes to stretch | set_reminder | set_reminder | {"message":"stretch","at":null,"in_minutes":10} | 3.7 s |
