# Model benchmark (tool routing: keywords)

Run on 2026-10-20 17:51, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 87 commands is sent once with the Jarvis system prompt and the tools keyword routing selects (all of them when nothing matches). A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 93% (81/87) | 2.7 s | 3.9 s | 18.7 s | 58%/42% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 2.3 s |
| can you launch vs code | open_app | **focus_app** | {} | 2.3 s |
| start docker | open_app | **docker_list** | {"include_stopped":true} | 2.7 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 2.4 s |
| bring up the calculator | open_app | **(no tool)** |  | 1.9 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.1 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 2.5 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 2.5 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"reviews RTX 3050 laptop GPU"} | 5.7 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 3.4 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 3.7 s |
| say hello | speak | speak | {"text":"hello"} | 2.2 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 2.8 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 2.8 s |
| open the app | (no tool) or ask_user | (no tool) |  | 3.1 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"python function search"} | 2.8 s |
| hi jarvis | (no tool) | (no tool) |  | 2.5 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 2.2 s |
| thanks, that's all | (no tool) | (no tool) |  | 5.2 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don't scientists trust atoms? Because they make | 3.4 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 2.5 s |
| close the calculator | close_app | **(no tool)** |  | 1.9 s |
| what docker containers are running | docker_list | docker_list | {"include_stopped":true} | 2.7 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 2.2 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend","lines":10} | 3.3 s |
| find my resume | find_file | find_file | {"kind":"file","query":"resume"} | 3.4 s |
| open the jarvis readme | find_file or open_file | find_file | {"kind":"file","query":"readme"} | 3.1 s |
| what is this file | get_selected_file | get_selected_file | {} | 2.0 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 2.9 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"line":null,"path":"jarvis project folder"} | 3.0 s |
| what's reliance trading at | market_data | market_data | {"query":"Reliance"} | 2.6 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 2.2 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 2.8 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"coin":"bitcoin","currency":"rupees"} | 3.4 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"amount":100,"from_currency":"dollars","to_currency":"rupee | 4.5 s |
| what's the weather tomorrow | weather | weather | {"day":"tomorrow"} | 2.2 s |
| is it going to rain in mumbai today | weather | weather | {"day":"today","place":"Mumbai"} | 2.9 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 2.9 s |
| set the volume to 30 | set_volume | set_volume | {"level":30} | 2.6 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 2.3 s |
| lock my laptop | lock_screen | lock_screen | {} | 2.0 s |
| take a screenshot | screenshot | screenshot | {} | 1.9 s |
| what did I copy | clipboard_read | clipboard_read | {"about":"copy"} | 2.7 s |
| set a timer for 5 minutes | set_timer | set_timer | {"label":"timer","minutes":5,"seconds":0} | 3.5 s |
| remind me in 10 minutes to stretch | set_reminder | set_reminder | {"at":null,"in_minutes":10,"message":"stretch"} | 3.7 s |
| type hello world in notepad | type_text | type_text | {"text":"hello world","app":"notepad","field":null} | 3.9 s |
| click the File menu in notepad | click | click | {"app":"notepad","target":"File"} | 4.0 s |
| press ctrl s in notepad | press_keys | press_keys | {"app":"notepad","keys":"ctrl+s"} | 3.3 s |
| what does the notepad window say | read_window_text | read_window_text | {"app":"notepad"} | 3.0 s |
| message mom that I'll be late | send_whatsapp | send_whatsapp | {"contact":"Mom","message":"I'll be late"} | 3.2 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | {"contact":"Ravi","message":"the meeting moved to 5"} | 4.3 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | send_whatsapp | {"message":"I reached home","contact":"dad"} | 3.7 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | **search_site** | {"query":"wireless earbuds","site":"amazon"} | 3.9 s |
| open github.com in your browser so you can sign me in | browser_open | browser_open | {"url":"github.com"} | 3.2 s |
| on the page in your browser, click today's deals | browser_click or browser_read | browser_click | {"app":"browser","target":"today's deals"} | 4.3 s |
| what does the page in your browser say | browser_read | browser_read | {} | 2.3 s |
| read my notifications | read_notifications | read_notifications | {"person":null} | 2.2 s |
| anything new from Ravi | read_notifications | read_notifications | {"person":"Ravi"} | 2.1 s |
| did mom message me | read_notifications | read_notifications | {"person":"Mom"} | 2.1 s |
| remember that my manager is Ravi | remember | remember | {"fact":"The user's manager is Ravi"} | 2.9 s |
| what do you remember about me | list_memories | list_memories | {} | 2.1 s |
| forget that my manager is Ravi | forget | forget | {"what":"my manager"} | 2.6 s |
| search youtube for lofi music | search_site | search_site | {"site":"youtube","query":"lofi music"} | 3.6 s |
| open wikipedia and search for alan turing | search_site | search_site | {"site":"wikipedia","query":"alan turing"} | 3.6 s |
| find running shoes on amazon | search_site | search_site | {"site":"amazon","query":"running shoes"} | 3.1 s |
| call mom | call_contact | call_contact | {"contact":"mom"} | 2.1 s |
| phone ravi please | call_contact | call_contact | {"contact":"ravi"} | 2.2 s |
| could you skip to the next track | media_control | media_control | {"action":"next"} | 2.6 s |
| resume the song I was listening to | media_control | media_control | {"action":"play"} | 2.6 s |
| pause the video in brave | media_control | media_control | {"action":"pause"} | 2.3 s |
| which song is playing right now | now_playing | now_playing | {} | 2.1 s |
| any new email | read_mail | read_mail | {"unread_only":true} | 2.7 s |
| check my emails from ravi | read_mail | read_mail | {"unread_only":true,"sender":"ravi"} | 2.9 s |
| read the email about the project update | read_email or read_mail | read_email | {"message":"the project update"} | 3.0 s |
| reply to ravi's email that I'll send the report tonight | read_email or read_mail or reply_email | reply_email | {"function":"reply_email","arguments":{"message":"Ravi","rep | 4.8 s |
| what's on my calendar today | calendar_events | calendar_events | {"day":"today"} | 2.2 s |
| what's my next meeting | calendar_events | calendar_events | {"day":"next"} | 2.0 s |
| am I free on friday | calendar_events | calendar_events | {"day":"friday"} | 2.4 s |
| what did I ask about docker last week | recall | recall | {"about":"docker","when":"last week"} | 2.8 s |
| when did I last ask you about the weather | recall | recall | {"about":"the weather"} | 2.4 s |
| give me a rundown of my day | briefing | briefing | {"type":"briefing"} | 2.8 s |
| what have I got lined up tomorrow | calendar_events | calendar_events | {"day":"tomorrow"} | 2.4 s |
| anything booked for friday evening | calendar_events | calendar_events | {"day":"friday"} | 2.7 s |
| is it going to pour in mumbai later | weather | weather | {"place":"Mumbai"} | 2.9 s |
| it's too loud, bring it down | set_volume | set_volume | {"change":-10} | 2.3 s |
| has anybody tried to reach me | read_mail or read_notifications | read_notifications | {"person":"you"} | 2.3 s |
| drop my sister a line saying I'm home | send_whatsapp | send_whatsapp | {"contact":"sister","message":"I'm home"} | 2.9 s |
