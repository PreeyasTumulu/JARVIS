# Model benchmark (tool routing: keywords)

Run on 2026-10-20 10:26, NVIDIA GeForce RTX 3050 Laptop GPU, 4096 MiB. Each of 86 commands is sent once with the Jarvis system prompt and the tools keyword routing selects (all of them when nothing matches). A case is correct if the first tool call (or no call) matches what a careful assistant would do, including a key argument where noted. Nothing is executed. Other models are unloaded first, so load time is a cold start and placement is the model alone.

Regenerate with `uv run python scripts/benchmark_tools.py`.

## Summary

| Model | Accuracy | Median latency | p90 latency | Load time | Placement | Text fallback |
|---|---|---|---|---|---|---|
| `jarvis-hermes3` | 92% (79/86) | 4.3 s | 8.0 s | 28.2 s | 58%/42% CPU/GPU | 0 |

## `jarvis-hermes3` details

| Command | Expected | Got | Args | Time |
|---|---|---|---|---|
| open notepad | open_app | open_app | {"name":"notepad"} | 3.3 s |
| can you launch vs code | open_app | **focus_app** | {} | 3.4 s |
| start docker | open_app | **docker_list** | {"include_stopped":true} | 4.4 s |
| open whatsapp please | open_app | open_app | {"name":"whatsapp"} | 3.5 s |
| bring up the calculator | open_app | **(no tool)** |  | 2.7 s |
| open chrome | open_app | open_app | {"name":"chrome"} | 2.9 s |
| search the web for the latest python release | web_search | web_search | {"query":"latest python release"} | 3.7 s |
| who won the most recent cricket world cup | web_search | web_search | {"query":"most recent cricket world cup winner"} | 4.1 s |
| find reviews of the RTX 3050 laptop GPU | web_search | web_search | {"query":"RTX 3050 laptop GPU reviews"} | 6.6 s |
| what is the latest news about OpenAI | web_search | web_search | {"query":"latest news about OpenAI"} | 4.2 s |
| look up how tall the Burj Khalifa is | web_search | web_search | {"query":"how tall is the Burj Khalifa"} | 4.2 s |
| say hello | speak | speak | {"text":"hello"} | 2.9 s |
| read this out loud: the build passed | speak | speak | {"text":"the build passed"} | 4.2 s |
| announce that the meeting starts in five minutes | speak | speak | {"text":"The meeting starts in five minutes"} | 3.7 s |
| open the app | (no tool) or ask_user | (no tool) |  | 3.5 s |
| search for it | (no tool) or ask_user | **web_search** | {"query":"python function to search for a string in a file"} | 3.8 s |
| hi jarvis | (no tool) | (no tool) |  | 3.0 s |
| what is 15 times 12 | (no tool) | (no tool) |  | 4.9 s |
| thanks, that's all | (no tool) | (no tool) |  | 6.7 s |
| tell me a one line joke | (no tool) or speak | speak | {"text":"Why don't scientists trust atoms? Because they make | 8.2 s |
| switch to vs code | focus_app | focus_app | {"name":"vs code"} | 3.5 s |
| close the calculator | close_app | **(no tool)** |  | 2.2 s |
| what docker containers are running | docker_list | docker_list | {"include_stopped":true} | 4.0 s |
| stop the postgres container | docker_stop | docker_stop | {"container":"postgres"} | 3.0 s |
| show me the logs of the backend container | docker_logs | docker_logs | {"container":"backend","lines":10} | 4.3 s |
| find my resume | find_file | find_file | {"kind":"file","query":"resume"} | 5.7 s |
| open the jarvis readme | find_file or open_file | find_file | {"kind":"file","query":"readme"} | 6.0 s |
| what is this file | get_selected_file | get_selected_file | {} | 2.6 s |
| open github.com | open_url | open_url | {"url":"github.com"} | 6.3 s |
| open the jarvis project folder in vs code | find_file or vscode_open | vscode_open | {"line":null,"path":"jarvis project folder"} | 4.6 s |
| what's reliance trading at | market_data | market_data | {"query":"Reliance"} | 4.5 s |
| price of apple stock | market_data | market_data | {"query":"Apple"} | 3.6 s |
| how is the nifty doing today | market_data | market_data | {"query":"Nifty 50"} | 4.0 s |
| bitcoin price in rupees | crypto_price | crypto_price | {"currency":"rupees","coin":"bitcoin"} | 4.3 s |
| convert 100 dollars to rupees | convert_currency | convert_currency | {"from_currency":"dollars","to_currency":"rupees","amount":1 | 5.7 s |
| what's the weather tomorrow | weather | weather | {"day":"tomorrow","place":null} | 4.1 s |
| is it going to rain in mumbai today | weather | weather | {"day":"today","place":"Mumbai"} | 5.1 s |
| summarize https://www.python.org/about/ | fetch_page | fetch_page | {"url":"https://www.python.org/about/"} | 5.1 s |
| set the volume to 30 | set_volume | set_volume | {"level":30} | 4.7 s |
| make the screen dimmer | set_brightness | set_brightness | {"change":-10} | 3.3 s |
| lock my laptop | lock_screen | lock_screen | {} | 3.2 s |
| take a screenshot | screenshot | screenshot | {} | 2.6 s |
| what did I copy | clipboard_read | clipboard_read | {} | 2.9 s |
| set a timer for 5 minutes | set_timer | set_timer | {"minutes":5,"seconds":0,"label":"timer"} | 7.0 s |
| remind me in 10 minutes to stretch | set_reminder | set_reminder | {"at":null,"in_minutes":10,"message":"stretch"} | 5.7 s |
| type hello world in notepad | type_text | type_text | {"field":null,"text":"hello world","app":"notepad"} | 6.1 s |
| click the File menu in notepad | click | click | {"app":"notepad","target":"File"} | 5.8 s |
| press ctrl s in notepad | press_keys | press_keys | {"app":"notepad","keys":"ctrl+s"} | 6.8 s |
| what does the notepad window say | read_window_text | read_window_text | {"app":"notepad"} | 6.3 s |
| message mom that I'll be late | send_whatsapp | send_whatsapp | {"contact":"Mom","message":"I'll be late"} | 4.6 s |
| tell Ravi on whatsapp that the meeting moved to 5 | send_whatsapp | send_whatsapp | {"contact":"Ravi","message":"the meeting moved to 5"} | 6.2 s |
| send a whatsapp to dad saying I reached home | send_whatsapp | send_whatsapp | {"contact":"dad","message":"I reached home"} | 4.5 s |
| search amazon for wireless earbuds in your browser | browser_open or browser_type | **search_site** | {"query":"wireless earbuds","site":"amazon"} | 5.6 s |
| open github.com in your browser so you can sign me in | browser_open | browser_open | {"url":"https://github.com","search":"https://github.com/log | 10.3 s |
| on the page in your browser, click today's deals | browser_click or browser_read | **browser_open** | {"url":"https://www.amazon.in","search":"today's deals"} | 8.0 s |
| what does the page in your browser say | browser_read | browser_read | {} | 3.4 s |
| read my notifications | read_notifications | read_notifications | {"person":null} | 3.2 s |
| anything new from Ravi | read_notifications | read_notifications | {"person":"Ravi"} | 3.2 s |
| did mom message me | read_notifications | read_notifications | {"person":"Mom"} | 3.3 s |
| remember that my manager is Ravi | remember | remember | {"fact":"The user's manager is Ravi"} | 4.8 s |
| what do you remember about me | list_memories | list_memories | {} | 3.6 s |
| forget that my manager is Ravi | forget | forget | {"what":"my manager is Ravi"} | 3.6 s |
| search youtube for lofi music | search_site | search_site | {"site":"youtube","query":"lofi music"} | 7.1 s |
| open wikipedia and search for alan turing | search_site | search_site | {"site":"wikipedia","query":"alan turing"} | 6.6 s |
| find running shoes on amazon | search_site | search_site | {"site":"amazon","query":"running shoes"} | 6.0 s |
| call mom | call_contact | call_contact | {"contact":"mom"} | 3.6 s |
| phone ravi please | call_contact | call_contact | {"contact":"ravi"} | 3.3 s |
| could you skip to the next track | media_control | media_control | {"action":"next"} | 3.7 s |
| resume the song I was listening to | media_control | media_control | {"action":"play"} | 4.1 s |
| pause the video in brave | media_control | media_control | {"action":"pause"} | 3.4 s |
| which song is playing right now | now_playing | now_playing | {} | 2.6 s |
| any new email | read_mail | read_mail | {"unread_only":true} | 3.7 s |
| check my emails from ravi | read_mail | read_mail | {"sender":"ravi","unread_only":true} | 4.4 s |
| read the email about the project update | read_email or read_mail | read_email | {"message":"the project update"} | 4.5 s |
| reply to ravi's email that I'll send the report tonight | read_email or read_mail or reply_email | reply_email | {"function":"reply_email","arguments":{"message":"Ravi","rep | 7.9 s |
| what's on my calendar today | calendar_events | calendar_events | {"day":"today"} | 3.3 s |
| what's my next meeting | calendar_events | calendar_events | {"day":"next"} | 3.1 s |
| am I free on friday | calendar_events | calendar_events | {"day":"friday"} | 3.2 s |
| any open issues on my JARVIS repo on github | github_get_me or github_list_issues or github_search_issues | github_list_issues | {"repo":"JARVIS","owner":"my"} | 8.8 s |
| show the pull requests on PreeyasTumulu/JARVIS | github_list_pull_requests | github_list_pull_requests | {"repo":"JARVIS","state":"open","owner":"PreeyasTumulu"} | 9.2 s |
| who am I on github | github_get_me | github_get_me | {} | 4.9 s |
| open a github issue on PreeyasTumulu/JARVIS titled wake word misses quiet voices | github_issue_write | github_issue_write | {"owner":"PreeyasTumulu","repo":"JARVIS","title":"wake word  | 8.8 s |
| what were the last commits on PreeyasTumulu/JARVIS | github_list_commits | github_list_commits | {"owner":"PreeyasTumulu","repo":"JARVIS"} | 8.5 s |
| find github repos about wake word detection | github_search_repositories | github_search_repositories | {"query":"wake word detection"} | 5.8 s |
| read issue 12 on PreeyasTumulu/JARVIS | github_issue_read | github_issue_read | {"issue_number":12,"owner":"PreeyasTumulu","repo":"JARVIS"} | 9.0 s |
| comment on issue 12 in PreeyasTumulu/JARVIS that it is fixed | github_add_issue_comment | github_add_issue_comment | {"issue_number":12,"body":"This issue is now fixed.","owner" | 9.0 s |
