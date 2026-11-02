# Model benchmark (tool routing: keywords)

Run on 2026-10-20 09:37, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 78 commands is sent once with the Jarvis system prompt and the tools keyword routing selects (all of them when nothing matches). A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 92% (72/78) | 2.8 s | 4.1 s | 17.4 s | 58%/42% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 2.2 s |
| can you launch vs code | open_app | **focus_app** | {} | 2.3 s |
| start docker | open_app | **docker_list** | {"include_stopped":true} | 2.7 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 2.3 s |
| bring up the calculator | open_app | **(no tool)** |  | 1.8 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.2 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 2.5 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 2.5 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"RTX 3050 laptop GPU reviews"} | 6.1 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 3.3 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 3.6 s |
| say hello | speak | speak | {"text":"hello"} | 2.2 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 2.8 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 3.0 s |
| open the app | (no tool) or ask_user | (no tool) |  | 3.1 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"current events"} | 2.8 s |
| hi jarvis | (no tool) | (no tool) |  | 2.5 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 4.4 s |
| thanks, that's all | (no tool) | (no tool) |  | 4.8 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don't scientists trust atoms? Because they make | 5.8 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 3.0 s |
| close the calculator | close_app | **(no tool)** |  | 2.1 s |
| what docker containers are running | docker_list | docker_list | {"include_stopped":true} | 2.8 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 2.3 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend","lines":10} | 3.4 s |
| find my resume | find_file | find_file | {"kind":"file","query":"resume"} | 3.4 s |
| open the jarvis readme | find_file or open_file | find_file | {"query":"readme","kind":"file"} | 3.3 s |
| what is this file | get_selected_file | get_selected_file | {} | 2.0 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 2.9 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"line":null,"path":"jarvis project folder"} | 3.0 s |
| what's reliance trading at | market_data | market_data | {"query":"Reliance"} | 2.7 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 2.3 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 3.1 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"coin":"bitcoin","currency":"rupees"} | 3.6 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"amount":100,"from_currency":"dollars","to_currency":"rupee | 4.7 s |
| what's the weather tomorrow | weather | weather | {"day":"tomorrow"} | 2.3 s |
| is it going to rain in mumbai today | weather | weather | {"place":"Mumbai","day":"today"} | 3.0 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 3.0 s |
| set the volume to 30 | set_volume | set_volume | {"level":30} | 2.7 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 2.4 s |
| lock my laptop | lock_screen | lock_screen | {} | 2.1 s |
| take a screenshot | screenshot | screenshot | {} | 2.1 s |
| what did I copy | clipboard_read | clipboard_read | {} | 2.2 s |
| set a timer for 5 minutes | set_timer | set_timer | {"label":"timer","minutes":5,"seconds":0} | 3.9 s |
| remind me in 10 minutes to stretch | set_reminder | set_reminder | {"in_minutes":10,"message":"stretch","at":null} | 4.1 s |
| type hello world in notepad | type_text | type_text | {"app":"notepad","field":null,"text":"hello world"} | 4.0 s |
| click the File menu in notepad | click | click | {"app":"notepad","target":"File"} | 4.0 s |
| press ctrl s in notepad | press_keys | press_keys | {"app":"notepad","keys":"ctrl+s"} | 3.5 s |
| what does the notepad window say | read_window_text | read_window_text | {"app":"notepad"} | 3.1 s |
| message mom that I'll be late | send_whatsapp | send_whatsapp | {"contact":"Mom","message":"I'll be late"} | 3.1 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | {"contact":"Ravi","message":"the meeting moved to 5"} | 4.0 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | send_whatsapp | {"contact":"dad","message":"I reached home"} | 4.0 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | **search_site** | {"query":"wireless earbuds","site":"amazon"} | 4.0 s |
| open github.com in your browser so you can sign me in | browser_open | browser_open | {"url":"github.com"} | 3.3 s |
| on the page in your browser, click today's deals | browser_click or browser_read | browser_click | {"url":"https://www.amazon.in/","target":"Today's Deals"} | 4.8 s |
| what does the page in your browser say | browser_read | browser_read | {} | 2.6 s |
| read my notifications | read_notifications | read_notifications | {"person":null} | 2.3 s |
| anything new from Ravi | read_notifications | read_notifications | {"person":"Ravi"} | 2.1 s |
| did mom message me | read_notifications | read_notifications | {"person":"Mom"} | 2.1 s |
| remember that my manager is Ravi | remember | remember | {"fact":"The user's manager is Ravi"} | 2.6 s |
| what do you remember about me | list_memories | list_memories | {} | 2.0 s |
| forget that my manager is Ravi | forget | forget | {"what":"my manager is Ravi"} | 3.0 s |
| search youtube for lofi music | search_site | search_site | {"site":"youtube","query":"lofi music"} | 3.7 s |
| open wikipedia and search for alan turing | search_site | search_site | {"site":"wikipedia","query":"alan turing"} | 3.6 s |
| find running shoes on amazon | search_site | search_site | {"site":"amazon","query":"running shoes"} | 3.2 s |
| call mom | call_contact | call_contact | {"contact":"mom"} | 2.1 s |
| phone ravi please | call_contact | call_contact | {"contact":"ravi"} | 2.3 s |
| could you skip to the next track | media_control | media_control | {"action":"next"} | 2.4 s |
| resume the song I was listening to | media_control | media_control | {"action":"play"} | 2.7 s |
| pause the video in brave | media_control | media_control | {"action":"pause"} | 2.4 s |
| which song is playing right now | now_playing | now_playing | {} | 2.3 s |
| any new email | read_mail | read_mail | {"unread_only":true} | 2.7 s |
| check my emails from ravi | read_mail | read_mail | {"sender":"ravi","unread_only":true} | 3.2 s |
| read the email about the project update | read_email or read_mail | read_email | {"message":"the project update"} | 3.0 s |
| reply to ravi's email that I'll send the report tonight | read_email or read_mail or reply_email | reply_email | {"function":"reply_email","arguments":{"message":"Ravi","rep | 4.9 s |
| what's on my calendar today | calendar_events | calendar_events | {"day":"today"} | 2.2 s |
| what's my next meeting | calendar_events | calendar_events | {"day":"next"} | 2.2 s |
| am I free on friday | calendar_events | calendar_events | {"day":"friday"} | 2.6 s |
