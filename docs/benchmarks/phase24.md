# Model benchmark (tool routing: keywords)

Run on 2026-11-07 08:53, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 97 commands is sent once with the Jarvis system prompt and the tools keyword routing selects (all of them when nothing matches). A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 89% (86/97) | 3.0 s | 4.1 s | 22.8 s | 58%/42% CPU/GPU | 1 |
| `jarvis-hermes3-3b` | 14% (14/97) | 0.8 s | 1.5 s | 13.2 s | 20%/80% CPU/GPU | 13 |
| `llama3.2:3b` | 88% (85/97) | 0.4 s | 0.8 s | 10.1 s | 100% GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 2.4 s |
| can you launch vs code | open_app | **focus_app** | {} | 2.4 s |
| start docker | open_app | **docker_list** | {"include_stopped":true} | 2.8 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 2.5 s |
| bring up the calculator | open_app | **(no tool)** |  | 2.1 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.4 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 2.7 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 2.7 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"reviews RTX 3050 laptop GPU"} | 4.2 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 3.3 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 4.0 s |
| say hello | speak | speak | {"text":"hello"} | 2.4 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 3.0 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 3.1 s |
| open the app | (no tool) or ask_user | **open_app** | {"name": "notepad"} | 3.5 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"python function search"} | 3.2 s |
| hi jarvis | (no tool) | (no tool) |  | 2.1 s |
| what is 15 times 12 | (no tool) | **calculate** | {"numbers":["15","12"],"operation":"*"} | 3.1 s |
| thanks, that's all | (no tool) | (no tool) |  | 3.5 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don't scientists trust atoms? Because they make | 3.7 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 2.9 s |
| close the calculator | close_app | **(no tool)** |  | 2.2 s |
| what docker containers are running | docker_list | docker_list | {"include_stopped":true} | 3.0 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 2.5 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend","lines":10} | 3.8 s |
| find my resume | find_file | find_file | {"query":"resume","kind":"file"} | 3.6 s |
| open the jarvis readme | find_file or open_file | **open_app** | {"name":"notepad"} | 2.9 s |
| what is this file | get_selected_file | get_selected_file | {} | 2.1 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 3.0 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"line":null,"path":"jarvis project folder"} | 3.3 s |
| what's reliance trading at | market_data | market_data | {"query":"Reliance"} | 2.9 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 2.6 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 3.3 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"coin":"bitcoin","currency":"rupees"} | 3.9 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"amount":100,"from_currency":"dollars","to_currency":"rupee | 5.0 s |
| what's the weather tomorrow | weather | **(no tool)** |  | 3.1 s |
| is it going to rain in mumbai today | weather | weather | {"day":"today","place":"Mumbai"} | 3.6 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 3.1 s |
| set the volume to 30 | set_volume | set_volume | {"level":30} | 2.9 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 2.6 s |
| lock my laptop | lock_screen | lock_screen | {} | 2.2 s |
| take a screenshot | screenshot | screenshot | {} | 2.3 s |
| what did I copy | clipboard_read | **clipboard_history** | {"count":5} | 3.3 s |
| set a timer for 5 minutes | set_timer | set_timer | {"label":"timer","minutes":5,"seconds":0} | 4.0 s |
| remind me in 10 minutes to stretch | set_reminder | set_reminder | {"at":null,"in_minutes":10,"message":"stretch"} | 4.3 s |
| type hello world in notepad | type_text | type_text | {"app":"notepad","field":null,"text":"hello world"} | 4.3 s |
| click the File menu in notepad | click | click | {"app":"notepad","target":"File"} | 4.1 s |
| press ctrl s in notepad | press_keys | press_keys | {"app":"notepad","keys":"ctrl+s"} | 3.7 s |
| what does the notepad window say | read_window_text | read_window_text | {"app":"notepad"} | 3.3 s |
| message mom that I'll be late | send_whatsapp | send_whatsapp | {"contact":"Mom","message":"I'll be late"} | 4.0 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | {"contact":"Ravi","message":"the meeting moved to 5"} | 5.0 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | send_whatsapp | {"contact":"dad","message":"I reached home"} | 4.2 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | **search_site** | {"site":"amazon","query":"wireless earbuds"} | 4.2 s |
| open github.com in your browser so you can sign me in | browser_open | browser_open | {"url":"github.com"} | 3.5 s |
| on the page in your browser, click today's deals | browser_click or browser_read | browser_click | {"url":"https://www.amazon.in/","target":"Today's Deals"} | 4.9 s |
| what does the page in your browser say | browser_read | browser_read | {} | 2.6 s |
| read my notifications | read_notifications | read_notifications | {"person":null} | 2.4 s |
| anything new from Ravi | read_notifications | read_notifications | {"person":"Ravi"} | 2.5 s |
| did mom message me | read_notifications | read_notifications | {"person":"Mom"} | 2.4 s |
| remember that my manager is Ravi | remember | remember | {"fact":"The user's manager is Ravi","about":"user"} | 4.0 s |
| what do you remember about me | list_memories | list_memories | {} | 2.5 s |
| forget that my manager is Ravi | forget | forget | {"what":"my manager"} | 3.1 s |
| forget what I asked about docker | forget_history | forget_history | {"about":"docker","when":"today"} | 3.2 s |
| delete yesterday's commands | forget_history | forget_history | {"about":"yesterday's commands","when":"yesterday"} | 3.8 s |
| clear my command history | forget_history | forget_history | {"about":"everything","when":"yesterday"} | 3.8 s |
| what did I copy earlier | clipboard_history | clipboard_history | {"count":5} | 2.7 s |
| put the second last thing I copied back on the clipboard | clipboard_restore | clipboard_restore | {"position":2} | 2.4 s |
| start a 50 minute focus session | focus_start | focus_start | {"minutes":50} | 2.4 s |
| how long is left in my focus session | focus_status | focus_status | {} | 2.2 s |
| search youtube for lofi music | search_site | search_site | {"site":"youtube","query":"lofi music"} | 3.8 s |
| open wikipedia and search for alan turing | search_site | search_site | {"site":"wikipedia","query":"alan turing"} | 3.9 s |
| find running shoes on amazon | search_site | search_site | {"site":"amazon","query":"running shoes"} | 3.5 s |
| call mom | call_contact | call_contact | {"contact":"mom"} | 2.4 s |
| phone ravi please | call_contact | call_contact | {"contact":"ravi"} | 2.7 s |
| could you end this call for me | hang_up | hang_up | {} | 2.2 s |
| could you skip to the next track | media_control | media_control | {"action":"next"} | 2.4 s |
| resume the song I was listening to | media_control | media_control | {"action":"play"} | 2.9 s |
| pause the video in brave | media_control | media_control | {"action":"pause"} | 2.9 s |
| which song is playing right now | now_playing | now_playing | {} | 2.6 s |
| any new email | read_mail | read_mail | {"unread_only":true} | 3.1 s |
| check my emails from ravi | read_mail | read_mail | {"sender":"ravi","unread_only":true} | 3.6 s |
| read the email about the project update | read_email or read_mail | read_email | {"message":"the project update"} | 3.6 s |
| reply to ravi's email that I'll send the report tonight | read_email or read_mail or reply_email | reply_email | {"function":"reply_email","arguments":{"message":"Ravi","rep | 5.6 s |
| what's on my calendar today | calendar_events | calendar_events | {"day":"today"} | 2.8 s |
| what's my next meeting | calendar_events | calendar_events | {"day":"next"} | 2.3 s |
| am I free on friday | calendar_events | calendar_events | {"day":"friday"} | 3.0 s |
| what's on my screen | read_screen | read_screen | {} | 2.6 s |
| read my screen to me | read_screen | read_screen | {} | 2.6 s |
| what did I ask about docker last week | recall | recall | {"about":"docker","when":"last week"} | 3.2 s |
| when did I last ask you about the weather | recall | recall | {"about":"the weather"} | 2.9 s |
| give me a rundown of my day | briefing | briefing | {"type":"briefing"} | 3.3 s |
| what have I got lined up tomorrow | calendar_events | calendar_events | {"day":"tomorrow"} | 3.2 s |
| anything booked for friday evening | calendar_events | calendar_events | {"day":"friday"} | 3.3 s |
| is it going to pour in mumbai later | weather | weather | {"place":"Mumbai"} | 3.0 s |
| it's too loud, bring it down | set_volume | set_volume | {"change":-10} | 2.4 s |
| has anybody tried to reach me | read_mail or read_notifications | read_notifications | {"person":"you"} | 2.5 s |
| drop my sister a line saying I'm home | send_whatsapp | send_whatsapp | {"contact":"sister","message":"I'm home"} | 3.4 s |

## `jarvis-hermes3-3b` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | **(no tool)** |  | 1.1 s |
| can you launch vs code | open_app | **(no tool)** |  | 0.9 s |
| start docker | open_app | **(no tool)** |  | 0.8 s |
| open whatsapp please | open_app | **(no tool)** |  | 1.1 s |
| bring up the calculator | open_app | **(no tool)** |  | 0.4 s |
| open chrome | open_app | **(no tool)** |  | 0.5 s |
| search the web for the latest python release | web_search | **(no tool)** |  | 0.9 s |
| who won the most recent cricket world cup | web_search | **(no tool)** |  | 0.9 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"function": "web_search", "query": "reviews of the nvidia r | 1.2 s |
| what is the latest news about OpenAI | web_search | **(no tool)** |  | 0.9 s |
| look up how tall the Burj Khalifa is | web_search | **(no tool)** |  | 0.3 s |
| say hello | speak | **(no tool)** |  | 0.6 s |
| read this out loud: the build passed | speak | **(no tool)** |  | 0.5 s |
| announce that the meeting starts in five minutes | speak | **(no tool)** |  | 0.4 s |
| open the app | (no tool) or ask_user | (no tool) |  | 0.4 s |
| search for it | (no tool) or ask_user | **error** | The model server returned an error (500). | 0.0 s |
| hi jarvis | (no tool) | **start** | {"type": "object", "properties": {"name": {"type": "string", | 2.6 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 0.7 s |
| thanks, that's all | (no tool) | (no tool) |  | 7.3 s |
| tell me a one line joke | (no tool) or speak | (no tool) |  | 1.1 s |
| switch to vs code | focus_app | **(no tool)** |  | 0.6 s |
| close the calculator | close_app | **calculator** | name | 0.4 s |
| what docker containers are running | docker_list | **(no tool)** |  | 0.7 s |
| stop the postgres container | docker_stop | **(no tool)** |  | 1.4 s |
| show me the logs of the backend container | docker_logs | **(no tool)** |  | 0.6 s |
| find my resume | find_file | **(no tool)** |  | 0.9 s |
| open the jarvis readme | find_file or open_file | **(no tool)** |  | 1.7 s |
| what is this file | get_selected_file | **(no tool)** |  | 0.7 s |
| open github.com | open_url | **(no tool)** |  | 0.9 s |
| open the jarvis project folder in vs code | find_file or vscode_open | **(no tool)** |  | 0.6 s |
| what's reliance trading at | market_data | **(no tool)** |  | 1.6 s |
| price of apple stock | market_data | **(no tool)** |  | 1.0 s |
| how is the nifty doing today | market_data | **(no tool)** |  | 0.7 s |
| bitcoin price in rupees | crypto_price | **(no tool)** |  | 2.9 s |
| convert 100 dollars to rupees | convert_currency | **(no tool)** |  | 0.4 s |
| what's the weather tomorrow | weather | **(no tool)** |  | 0.7 s |
| is it going to rain in mumbai today | weather | **(no tool)** |  | 0.6 s |
| summarize https://www.python.org/about/ | fetch_page | **(no tool)** |  | 0.9 s |
| set the volume to 30 | set_volume | **(no tool)** |  | 0.9 s |
| make the screen dimmer | set_brightness | **(no tool)** |  | 0.5 s |
| lock my laptop | lock_screen | **(no tool)** |  | 0.6 s |
| take a screenshot | screenshot | **(no tool)** |  | 0.4 s |
| what did I copy | clipboard_read | **(no tool)** |  | 0.9 s |
| set a timer for 5 minutes | set_timer | **(no tool)** |  | 0.7 s |
| remind me in 10 minutes to stretch | set_reminder | **(no tool)** |  | 0.6 s |
| type hello world in notepad | type_text | **(no tool)** |  | 0.9 s |
| click the File menu in notepad | click | **(no tool)** |  | 1.1 s |
| press ctrl s in notepad | press_keys | **(no tool)** |  | 0.6 s |
| what does the notepad window say | read_window_text | read_window_text | {"text": {"type": "null", "description": "Not required for t | 1.7 s |
| message mom that I'll be late | send_whatsapp | **(no tool)** |  | 0.8 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | { 'contact': 'Ravi', 'message': 'the meeting moved to 5', 'm | 0.8 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | **(no tool)** |  | 0.8 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | **(no tool)** |  | 1.0 s |
| open github.com in your browser so you can sign me in | browser_open | **(no tool)** |  | 1.0 s |
| on the page in your browser, click today's deals | browser_click or browser_read | **(no tool)** |  | 7.0 s |
| what does the page in your browser say | browser_read | **(no tool)** |  | 0.7 s |
| read my notifications | read_notifications | **(no tool)** |  | 0.7 s |
| anything new from Ravi | read_notifications | read_notifications | {"person": "Ravi"} | 0.5 s |
| did mom message me | read_notifications | **(no tool)** |  | 0.7 s |
| remember that my manager is Ravi | remember | **(no tool)** |  | 0.8 s |
| what do you remember about me | list_memories | **(no tool)** |  | 0.7 s |
| forget that my manager is Ravi | forget | **(no tool)** |  | 0.4 s |
| forget what I asked about docker | forget_history | **(no tool)** |  | 1.8 s |
| delete yesterday's commands | forget_history | **(no tool)** |  | 0.5 s |
| clear my command history | forget_history | **(no tool)** |  | 0.6 s |
| what did I copy earlier | clipboard_history | clipboard_history | {"count": 5} | 0.6 s |
| put the second last thing I copied back on the clipboard | clipboard_restore | clipboard_restore | {"position": 2} | 0.6 s |
| start a 50 minute focus session | focus_start | **(no tool)** |  | 0.7 s |
| how long is left in my focus session | focus_status | focus_status | {} | 0.4 s |
| search youtube for lofi music | search_site | **(no tool)** |  | 0.9 s |
| open wikipedia and search for alan turing | search_site | **(no tool)** |  | 1.1 s |
| find running shoes on amazon | search_site | **(no tool)** |  | 0.8 s |
| call mom | call_contact | **(no tool)** |  | 0.5 s |
| phone ravi please | call_contact | **(no tool)** |  | 0.4 s |
| could you end this call for me | hang_up | **function** | {"function": "hang_up"} | 0.8 s |
| could you skip to the next track | media_control | **(no tool)** |  | 0.7 s |
| resume the song I was listening to | media_control | **(no tool)** |  | 1.0 s |
| pause the video in brave | media_control | **(no tool)** |  | 0.6 s |
| which song is playing right now | now_playing | **(no tool)** |  | 0.6 s |
| any new email | read_mail | **(no tool)** |  | 0.9 s |
| check my emails from ravi | read_mail | **(no tool)** |  | 0.5 s |
| read the email about the project update | read_email or read_mail | **(no tool)** |  | 0.8 s |
| reply to ravi's email that I'll send the report tonight | read_email or read_mail or reply_email | **(no tool)** |  | 1.0 s |
| what's on my calendar today | calendar_events | **(no tool)** |  | 0.6 s |
| what's my next meeting | calendar_events | calendar_events | {"day": "next", "ask_user": "Can you please check your calen | 0.8 s |
| am I free on friday | calendar_events | **(no tool)** |  | 1.1 s |
| what's on my screen | read_screen | read_screen | {"function": "read_screen", "change": null, "level": null, " | 1.5 s |
| read my screen to me | read_screen | **(no tool)** |  | 0.9 s |
| what did I ask about docker last week | recall | **(no tool)** |  | 1.2 s |
| when did I last ask you about the weather | recall | **(no tool)** |  | 0.9 s |
| give me a rundown of my day | briefing | **(no tool)** |  | 1.4 s |
| what have I got lined up tomorrow | calendar_events | **(no tool)** |  | 0.4 s |
| anything booked for friday evening | calendar_events | calendar_events | calendar_events | 0.3 s |
| is it going to pour in mumbai later | weather | **(no tool)** |  | 2.4 s |
| it's too loud, bring it down | set_volume | **(no tool)** |  | 0.6 s |
| has anybody tried to reach me | read_mail or read_notifications | **(no tool)** |  | 1.3 s |
| drop my sister a line saying I'm home | send_whatsapp | **(no tool)** |  | 0.7 s |

## `llama3.2:3b` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 0.8 s |
| can you launch vs code | open_app | open_app | {"name":"vs code"} | 0.5 s |
| start docker | open_app | **docker_start** | {} | 0.4 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 0.4 s |
| bring up the calculator | open_app | **focus_app** | {"name":"calculator"} | 0.3 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 0.3 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest Python release"} | 0.5 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 0.4 s |
| find reviews of the RTX 3050 laptop GPU | web_search | **browser_read** | {} | 5.4 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"OpenAI latest news"} | 0.4 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"Burj Khalifa height"} | 0.3 s |
| say hello | speak | speak | {"text":"hello"} | 0.3 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 0.6 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting is about to start in five minutes."} | 0.5 s |
| open the app | (no tool) or ask_user | **open_app** | {"name":"notepad"} | 0.5 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"search for it"} | 0.4 s |
| hi jarvis | (no tool) | **speak** | {"text":"Hi"} | 1.1 s |
| what is 15 times 12 | (no tool) | **calculate** | {"expression":"15*12"} | 0.5 s |
| thanks, that's all | (no tool) | (no tool) |  | 1.4 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don\\u2019t scientists carry umbrellas?"} | 0.6 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 0.6 s |
| close the calculator | close_app | close_app | {"name":"calculator"} | 0.3 s |
| what docker containers are running | docker_list | docker_list | {"include_stopped":null} | 0.4 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 0.2 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend","lines":100} | 0.3 s |
| find my resume | find_file | find_file | {"query":"resume","kind":"file"} | 0.7 s |
| open the jarvis readme | find_file or open_file | open_file | {"path":"find_file","kind":"file","query":"readme"} | 0.8 s |
| what is this file | get_selected_file | get_selected_file | {} | 0.4 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 0.9 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"kind":"folder","query":"jarvis project","path":"find_file" | 0.5 s |
| what's reliance trading at | market_data | market_data | {"query":"Reliance"} | 0.5 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 0.3 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 0.3 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"coin":"bitcoin","currency":"INR"} | 0.3 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"amount":100,"from_currency":"USD","to_currency":"INR"} | 0.4 s |
| what's the weather tomorrow | weather | weather | {"place":"null","day":"tomorrow"} | 0.4 s |
| is it going to rain in mumbai today | weather | weather | {"place":"Mumbai","day":"today"} | 0.4 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 0.6 s |
| set the volume to 30 | set_volume | set_volume | {"level":"30"} | 0.5 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":"-10","level":"null"} | 0.4 s |
| lock my laptop | lock_screen | lock_screen | {} | 0.2 s |
| take a screenshot | screenshot | screenshot | {} | 0.2 s |
| what did I copy | clipboard_read | **clipboard_history** | {"count":1} | 0.6 s |
| set a timer for 5 minutes | set_timer | set_timer | {"label":"timer","minutes":"5","seconds":"0"} | 0.7 s |
| remind me in 10 minutes to stretch | set_reminder | set_reminder | {"message":"stretch","at":"in 10 minutes"} | 0.4 s |
| type hello world in notepad | type_text | type_text | {"app":"notepad","text":"hello world"} | 0.7 s |
| click the File menu in notepad | click | click | {"app":"notepad","target":"File"} | 0.8 s |
| press ctrl s in notepad | press_keys | press_keys | {"keys":"ctrl+s","app":"notepad"} | 0.7 s |
| what does the notepad window say | read_window_text | read_window_text | {"app":"notepad"} | 0.6 s |
| message mom that I'll be late | send_whatsapp | send_whatsapp | {"contact":"Mom","message":"I'll be late"} | 0.5 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | {"message":"the meeting moved to 5","contact":"Ravi"} | 0.4 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | send_whatsapp | {"contact":"dad","message":"I reached home"} | 0.3 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | browser_open | {"url":"amazon.in","search":"wireless earbuds"} | 0.8 s |
| open github.com in your browser so you can sign me in | browser_open | browser_open | {"url":"github.com"} | 0.8 s |
| on the page in your browser, click today's deals | browser_click or browser_read | browser_click | {"target":"today"} | 0.8 s |
| what does the page in your browser say | browser_read | browser_read | {} | 0.2 s |
| read my notifications | read_notifications | read_notifications | {"person":null} | 0.4 s |
| anything new from Ravi | read_notifications | read_notifications | {"person":"Ravi"} | 0.4 s |
| did mom message me | read_notifications | read_notifications | {"person":"mom"} | 0.4 s |
| remember that my manager is Ravi | remember | **remember** | {"about":"user","fact":"The user"} | 0.5 s |
| what do you remember about me | list_memories | list_memories | {} | 0.2 s |
| forget that my manager is Ravi | forget | forget | {"what":"my manager"} | 0.2 s |
| forget what I asked about docker | forget_history | forget_history | {"about":"docker","when":"today"} | 0.4 s |
| delete yesterday's commands | forget_history | forget_history | {"about":"","when":"yesterday"} | 0.3 s |
| clear my command history | forget_history | forget_history | {"about":"","when":"today"} | 0.3 s |
| what did I copy earlier | clipboard_history | clipboard_history | {"count":5} | 0.6 s |
| put the second last thing I copied back on the clipboard | clipboard_restore | clipboard_restore | {"position":2} | 0.3 s |
| start a 50 minute focus session | focus_start | focus_start | {"minutes":"50"} | 0.4 s |
| how long is left in my focus session | focus_status | focus_status | {} | 0.2 s |
| search youtube for lofi music | search_site | search_site | {"site":"youtube","query":"lofi music"} | 0.8 s |
| open wikipedia and search for alan turing | search_site | **browser_open** | {"url":"wikipedia.org","search":"alan turing"} | 0.7 s |
| find running shoes on amazon | search_site | search_site | {"site":"amazon","query":"running shoes"} | 0.6 s |
| call mom | call_contact | call_contact | {"contact":"mom"} | 0.4 s |
| phone ravi please | call_contact | call_contact | {"contact":"Ravi"} | 0.2 s |
| could you end this call for me | hang_up | hang_up | {} | 0.5 s |
| could you skip to the next track | media_control | media_control | {"action":"next"} | 0.5 s |
| resume the song I was listening to | media_control | **media_control** | {"action":"resume"} | 0.6 s |
| pause the video in brave | media_control | media_control | {"action":"pause"} | 0.4 s |
| which song is playing right now | now_playing | now_playing | {} | 0.2 s |
| any new email | read_mail | read_mail | {"unread_only":"false"} | 0.5 s |
| check my emails from ravi | read_mail | read_mail | {"unread_only":"false","sender":"Ravi"} | 0.4 s |
| read the email about the project update | read_email or read_mail | read_email | {"message":"any new email"} | 0.7 s |
| reply to ravi's email that I'll send the report tonight | read_email or read_mail or reply_email | reply_email | {"message":"Ravi","reply_all":false,"text":"I'll send the re | 0.7 s |
| what's on my calendar today | calendar_events | calendar_events | {"day":"today"} | 0.4 s |
| what's my next meeting | calendar_events | calendar_events | {"day":"next"} | 0.3 s |
| am I free on friday | calendar_events | **calendar_events** | {"day":"this week"} | 0.3 s |
| what's on my screen | read_screen | read_screen | {} | 0.5 s |
| read my screen to me | read_screen | read_screen | {} | 0.7 s |
| what did I ask about docker last week | recall | recall | {"about":"docker","when":"last week"} | 0.5 s |
| when did I last ask you about the weather | recall | recall | {"about":"weather","when":"last ask"} | 0.3 s |
| give me a rundown of my day | briefing | briefing | {} | 0.3 s |
| what have I got lined up tomorrow | calendar_events | calendar_events | {"day":"tomorrow"} | 0.4 s |
| anything booked for friday evening | calendar_events | calendar_events | {"day":"this week"} | 0.3 s |
| is it going to pour in mumbai later | weather | weather | {"place":"Mumbai"} | 0.3 s |
| it's too loud, bring it down | set_volume | set_volume | {"change":"-10"} | 0.5 s |
| has anybody tried to reach me | read_mail or read_notifications | read_notifications | {"person":"me"} | 0.4 s |
| drop my sister a line saying I'm home | send_whatsapp | send_whatsapp | {"contact":"sister","message":"I’m home"} | 0.5 s |
