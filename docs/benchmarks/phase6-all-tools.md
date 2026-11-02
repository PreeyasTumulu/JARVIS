# Model benchmark (tool routing: all)

Run on 2026-10-15 13:59, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 56 commands is sent once with the Jarvis system prompt and all 40 tools. A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 77% (43/56) | 4.0 s | 4.9 s | 15.2 s | 58%/42% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 3.5 s |
| can you launch vs code | open_app | open_app | {"name":"vs code"} | 4.2 s |
| start docker | open_app | open_app | {"name":"Docker Desktop"} | 3.9 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 3.6 s |
| bring up the calculator | open_app | **focus_app** | {"name":"calculator"} | 3.5 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 3.4 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 4.4 s |
| who won the most recent cricket world cup | web_search | **(no tool)** |  | 3.5 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"RTX 3050 laptop GPU reviews"} | 4.9 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 4.6 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"Burj Khalifa height"} | 4.4 s |
| say hello | speak | speak | {"text":"hello"} | 3.5 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 4.1 s |
| announce that the meeting starts in five minutes | speak | **(no tool)** |  | 3.4 s |
| open the app | (no tool) or ask_user | **open_app** | {"name":"notepad"} | 3.6 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"search for it"} | 3.8 s |
| hi jarvis | (no tool) | (no tool) |  | 2.0 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 4.6 s |
| thanks, that's all | (no tool) | (no tool) |  | 3.9 s |
| tell me a one line joke | (no tool) or speak | speak | {"type":"joke"} | 3.8 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 3.8 s |
| close the calculator | close_app | close_app | {"name":"calculator"} | 3.8 s |
| what docker containers are running | docker_list | docker_list | {"include_stopped":true} | 3.9 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 3.6 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend"} | 4.0 s |
| find my resume | find_file | find_file | {"query":"resume","kind":"file"} | 4.3 s |
| open the jarvis readme | find_file or open_file | **open_app** | {"name":"jarvis"} | 3.7 s |
| what is this file | get_selected_file | get_selected_file | {} | 3.1 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 3.7 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"path":"jarvis"} | 4.4 s |
| what's reliance trading at | market_data | **(no tool)** |  | 3.5 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 4.0 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 4.5 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"currency":"rupees","coin":"bitcoin"} | 4.6 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"amount":100,"from_currency":"dollars","to_currency":"rupee | 6.0 s |
| what's the weather tomorrow | weather | weather | {"day":"tomorrow","place":null} | 4.2 s |
| is it going to rain in mumbai today | weather | weather | {"day":"today","place":"Mumbai"} | 4.6 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 4.6 s |
| set the volume to 30 | set_volume | **(no tool)** |  | 3.9 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 3.6 s |
| lock my laptop | lock_screen | lock_screen | {} | 2.8 s |
| take a screenshot | screenshot | screenshot | {} | 2.8 s |
| what did I copy | clipboard_read | clipboard_read | {} | 3.0 s |
| set a timer for 5 minutes | set_timer | **(no tool)** |  | 3.2 s |
| remind me in 10 minutes to stretch | set_reminder | **(no tool)** |  | 4.6 s |
| type hello world in notepad | type_text | type_text | {"text":"hello world","app":"notepad"} | 4.6 s |
| click the File menu in notepad | click | click | {"app":"notepad","target":"File"} | 4.6 s |
| press ctrl s in notepad | press_keys | press_keys | {"app":"notepad","keys":"ctrl+s"} | 4.7 s |
| what does the notepad window say | read_window_text | read_window_text | {"app":"notepad"} | 4.2 s |
| message mom that I'll be late | send_whatsapp | **(no tool)** |  | 5.1 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | {"contact":"Ravi","message":"tell Ravi that the meeting move | 6.5 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | **(no tool)** |  | 4.6 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | browser_open | {"url":"amazon.in","search":"wireless earbuds"} | 5.5 s |
| open github.com in your browser so you can sign me in | browser_open | **open_url** | {"url":"github.com"} | 4.3 s |
| on the page in your browser, click today's deals | browser_click or browser_read | browser_click | {"app":"browser","target":"today's deals"} | 5.2 s |
| what does the page in your browser say | browser_read | browser_read | {} | 3.0 s |
