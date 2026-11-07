# Model benchmark (tool routing: keywords)

Run on 2026-11-07 15:29, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 113 commands is sent once with the Jarvis system prompt and the tools keyword routing selects (all of them when nothing matches). A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 92% (104/113) | 2.9 s | 4.3 s | 62.2 s | 58%/42% CPU/GPU | 2 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 2.5 s |
| can you launch vs code | open_app | **open_app** | {} | 2.4 s |
| start docker | open_app | open_app | {"name":"docker"} | 2.9 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 2.5 s |
| bring up the calculator | open_app | **focus_app** | {"name":"calculator"} | 2.4 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.3 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 2.6 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 2.9 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"RTX 3050 laptop GPU reviews"} | 4.5 s |
| what is the latest news about OpenAI | ai_news or web_search | ai_news | {"query":"OpenAI latest news"} | 3.2 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 3.5 s |
| say hello | speak | speak | {"text":"hello"} | 2.3 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 3.0 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 3.4 s |
| open the app | (no tool) or ask_user | **open_app** | {"name": {"type": "string", "description": "The app name as  | 7.2 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"python function search"} | 3.1 s |
| hi jarvis | (no tool) | (no tool) |  | 2.2 s |
| what is 15 times 12 | (no tool) | **calculate** | {"expression":"15*12"} | 2.9 s |
| thanks, that's all | (no tool) | (no tool) |  | 4.2 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don't scientists trust atoms? Because they make | 3.7 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 2.9 s |
| close the calculator | close_app | close_app | {"name":"calculator"} | 2.6 s |
| what docker containers are running | docker_list | docker_list | {} | 2.4 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 2.5 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend","lines":10} | 3.7 s |
| find my resume | find_file | find_file | {"kind":"file","query":"resume"} | 3.5 s |
| open the jarvis readme | find_file or open_file | open_file | {"name":"jarvis readme"} | 3.0 s |
| what is this file | get_selected_file | get_selected_file | {} | 2.3 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 3.1 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"name":"jarvis project"} | 2.7 s |
| what's reliance trading at | market_data | market_data | {"query":"Reliance"} | 2.8 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 2.4 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 3.2 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"coin":"bitcoin","currency":"rupees"} | 3.6 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"amount":100,"from_currency":"dollars","to_currency":"rupee | 4.8 s |
| what's the weather tomorrow | weather | weather | {"day":"tomorrow","place":null} | 2.9 s |
| is it going to rain in mumbai today | weather | weather | {"day":"today","place":"Mumbai"} | 3.1 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 3.3 s |
| set the volume to 30 | set_volume | set_volume | {"level":30} | 2.8 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 2.6 s |
| lock my laptop | lock_screen | lock_screen | {} | 2.1 s |
| take a screenshot | screenshot | screenshot | {} | 2.6 s |
| what did I copy | clipboard_read | **clipboard_history** | {"count":5} | 3.0 s |
| set a timer for 5 minutes | set_timer | set_timer | {"minutes":5} | 3.0 s |
| remind me in 10 minutes to stretch | set_reminder | set_reminder | {"at":null,"in_minutes":10,"message":"stretch"} | 4.3 s |
| type hello world in notepad | type_text | type_text | {"field":null,"text":"hello world","app":"notepad"} | 4.4 s |
| click the File menu in notepad | click | click | {"app":"notepad","target":"File"} | 4.1 s |
| press ctrl s in notepad | press_keys | press_keys | {"app":"notepad","keys":"ctrl+s"} | 3.7 s |
| what does the notepad window say | read_window_text | read_window_text | {"app":"notepad"} | 3.3 s |
| message mom that I'll be late | send_whatsapp | send_whatsapp | {"contact":"Mom","message":"I'll be late"} | 3.7 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | {"contact":"Ravi","message":"the meeting moved to 5"} | 4.8 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | send_whatsapp | {"contact":"dad","message":"I reached home"} | 4.2 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | **search_site** | {"site":"amazon","query":"wireless earbuds"} | 4.2 s |
| open github.com in your browser so you can sign me in | browser_open | browser_open | {"url":"github.com"} | 3.4 s |
| on the page in your browser, click today's deals | browser_click or browser_read | browser_click | {"url":"https://www.amazon.in/","target":"Today's Deals"} | 4.9 s |
| what does the page in your browser say | browser_read | browser_read | {} | 2.6 s |
| read my notifications | read_notifications | read_notifications | {"person":"Ravi"} | 2.6 s |
| anything new from Ravi | read_notifications | read_notifications | {"person":"Ravi"} | 2.4 s |
| did mom message me | read_notifications | read_notifications | {"person":"Mom"} | 2.3 s |
| remember that my manager is Ravi | remember | remember | {"fact":"The user's manager is Ravi","about":"user"} | 3.9 s |
| what do you remember about me | list_memories | list_memories | {} | 2.3 s |
| forget that my manager is Ravi | forget | forget | {"what":"my manager"} | 2.9 s |
| forget what I asked about docker | forget_history | forget_history | {"about":"docker","when":"today"} | 3.1 s |
| delete yesterday's commands | forget_history | forget_history | {"about":"yesterday's commands","when":"yesterday"} | 3.6 s |
| clear my command history | forget_history | forget_history | {"about":"everything","when":"yesterday"} | 3.7 s |
| what did I copy earlier | clipboard_history | clipboard_history | {"count":5} | 2.9 s |
| put the second last thing I copied back on the clipboard | clipboard_restore | clipboard_restore | {"position":2} | 2.5 s |
| start a 50 minute focus session | focus_start | focus_start | {"minutes":50} | 2.4 s |
| how long is left in my focus session | focus_status | focus_status | {} | 2.2 s |
| search youtube for lofi music | search_site | search_site | {"site":"youtube","query":"lofi music"} | 4.4 s |
| open wikipedia and search for alan turing | search_site | search_site | {"site":"wikipedia","query":"alan turing"} | 4.9 s |
| find running shoes on amazon | search_site | search_site | {"site":"amazon","query":"running shoes"} | 3.4 s |
| call mom | call_contact | call_contact | {"contact":"mom"} | 2.5 s |
| phone ravi please | call_contact | call_contact | {"contact":"ravi"} | 2.5 s |
| could you end this call for me | hang_up | hang_up | {} | 2.2 s |
| could you skip to the next track | media_control | media_control | {"action":"next"} | 2.4 s |
| resume the song I was listening to | media_control | **media_control** | {"action":"resume"} | 3.2 s |
| pause the video in brave | media_control | media_control | {"action":"pause"} | 2.9 s |
| which song is playing right now | now_playing | now_playing | {} | 2.5 s |
| any new email | read_mail | read_mail | {"unread_only":true} | 2.8 s |
| check my emails from ravi | read_mail | read_mail | {"sender":"ravi","unread_only":true} | 3.3 s |
| read the email about the project update | read_email or read_mail | read_email | {"message":"the project update"} | 3.2 s |
| reply to ravi's email that I'll send the report tonight | read_email or read_mail or reply_email | reply_email | {"message":"Ravi","reply_all":false,"text":"reply that I'll  | 5.4 s |
| what's on my calendar today | calendar_events | calendar_events | {"day":"today"} | 2.5 s |
| what's my next meeting | calendar_events | calendar_events | {"day":"next"} | 2.3 s |
| am I free on friday | calendar_events | calendar_events | {"day":"friday"} | 2.8 s |
| what's on my screen | look_at_screen or read_screen | look_at_screen | {} | 2.6 s |
| read my screen to me | read_screen | read_screen | {} | 2.7 s |
| what did I ask about docker last week | recall | recall | {"about":"docker","when":"last week"} | 3.0 s |
| close spotify in 20 minutes | schedule_app | schedule_app | {"name":"spotify","action":"close","at":"20 minutes","in_min | 6.0 s |
| open vs code at 9 tomorrow | schedule_app | **schedule_app** | {"at":"tomorrow 9","name":"vs code"} | 4.0 s |
| what did I note yesterday | read_notes | read_notes | {"day":"yesterday"} | 3.7 s |
| open my notes | open_notes | open_notes | {} | 2.6 s |
| add groceries and 450 to my budget sheet | add_sheet_row | add_sheet_row | {"sheet":"Sheet1","values":["Groceries","450"],"file":"budge | 4.3 s |
| show 18 percent of 2400 in the calculator | calculator_show | calculator_show | {"expression":"18/100*2400"} | 3.3 s |
| open my resume | find_file or open_file | open_file | {"path":"my resume"} | 2.9 s |
| what's on my screen | look_at_screen or read_screen | look_at_screen | {} | 1.6 s |
| what does this error on my screen mean | look_at_screen | look_at_screen | {"question":"what does this error on my screen mean"} | 3.6 s |
| what's new in AI today | ai_news | ai_news | {"refresh":true} | 2.5 s |
| any tech news | ai_news | ai_news | {"refresh":true} | 2.2 s |
| find my phone | ring_phone | ring_phone | {"ring": true} | 2.3 s |
| send the clipboard to my phone | send_to_phone | send_to_phone | {"item":"clipboard"} | 3.0 s |
| send my resume to my phone | send_to_phone | send_to_phone | {"item":"resume"} | 3.6 s |
| notify my phone that the download is done | notify_phone | notify_phone | {"title":"Download Complete","message":"The download is fini | 4.1 s |
| remind me on my phone at 7 pm to call the bank | set_reminder | set_reminder | {"on_phone":true,"at":"7 pm","in_minutes":null,"message":"ca | 5.1 s |
| when did I last ask you about the weather | recall | recall | {"about":"the weather"} | 2.7 s |
| give me a rundown of my day | briefing | briefing | {"type":"briefing"} | 2.8 s |
| what have I got lined up tomorrow | calendar_events | calendar_events | {"day":"tomorrow"} | 2.6 s |
| anything booked for friday evening | calendar_events | calendar_events | {"day":"friday"} | 2.8 s |
| is it going to pour in mumbai later | weather | weather | {"place":"Mumbai"} | 3.2 s |
| it's too loud, bring it down | set_volume | set_volume | {"change":-10} | 2.5 s |
| has anybody tried to reach me | read_mail or read_notifications | read_notifications | {"person":"you"} | 2.4 s |
| drop my sister a line saying I'm home | send_whatsapp | send_whatsapp | {"contact":"sister","message":"I'm home"} | 3.1 s |
