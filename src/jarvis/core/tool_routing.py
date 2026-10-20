"""Send the model only the tool groups a request is about.

An 8B model picks the right tool far less often when it sees every tool at once (see
docs/benchmarks). Cheap keyword matching on the request selects one or more groups; a request
that matches nothing gets every tool, so routing can narrow the choice but never hide a tool
the model might need for an unusual request. The executor still accepts any registered tool.

Fallback groups (plain question words) only count when no specific group matched, so "what's
the weather" sees the weather tool rather than web search as well.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.tools.registry import Registry, Tool

ALWAYS = ("ask_user", "speak")


@dataclass(frozen=True)
class Group:
    tools: tuple[str, ...]
    pattern: re.Pattern[str]
    fallback: bool = False


GROUPS: dict[str, Group] = {
    "apps": Group(
        ("open_app", "focus_app", "close_app"),
        re.compile(
            r"\b(open|launch|start|run|close|quit|exit|switch|focus|bring up|go to|app|apps|"
            r"application|window)\b"
        ),
    ),
    "files": Group(
        ("find_file", "open_file", "read_file", "get_selected_file", "vscode_open"),
        re.compile(
            r"\b(file|files|document|documents|doc|docs|folder|pdf|resume|cv|readme|notes?|"
            r"report|invoice|this|selected|read|project|downloads|desktop|vs ?code|code)\b"
            r"|\.\w{2,4}\b"
        ),
    ),
    "docker": Group(
        ("docker_list", "docker_logs", "docker_start", "docker_stop", "open_app"),
        re.compile(r"\b(docker|containers?|compose|postgres|redis|mongo|mysql|nginx|images?)\b"),
    ),
    "web": Group(
        ("web_search", "open_url", "fetch_page"),
        re.compile(
            r"\b(search|look up|lookup|google|news|latest|website|site|web|page|article|link|"
            r"url|summari[sz]e|wiki\w*|browser)\b|https?://|\.(com|org|net|io|dev|in)\b"
        ),
    ),
    "market": Group(
        ("market_data", "crypto_price", "convert_currency"),
        re.compile(
            r"\b(stocks?|shares?|market|trading|traded|price|prices|worth|ticker|nifty|sensex|"
            r"nasdaq|dow|s ?& ?p|index|crypto\w*|bitcoin|btc|ethereum|eth|coins?|dogecoin|"
            r"solana|currency|currencies|convert|exchange rate|dollars?|rupees?|euros?|pounds?|"
            r"yen|usd|inr|eur|gbp)\b"
        ),
    ),
    "weather": Group(
        ("weather",),
        re.compile(
            r"\b(weather|temperature|forecast|rain\w*|sunny|cloudy|humid\w*|snow\w*|umbrella|"
            r"windy|degrees|hot|cold)\b"
        ),
    ),
    "system": Group(
        (
            "set_volume",
            "set_brightness",
            "lock_screen",
            "screenshot",
            "clipboard_read",
            "clipboard_write",
        ),
        re.compile(
            r"\b(volume|louder|quieter|softer|mute|unmute|sound|audio|speakers?|brightness|"
            r"brighter|dimmer|dim|screen|display|lock|screenshot|screen ?shot|clipboard|copy|"
            r"copied|paste)\b"
        ),
    ),
    "time": Group(
        ("set_timer", "set_reminder", "list_reminders", "cancel_reminder"),
        re.compile(
            r"\b(remind\w*|timers?|alarms?|countdown)\b"
            r"|\bin \d+(\.\d+)? ?(seconds?|secs?|minutes?|mins?|hours?|hrs?)\b"
            r"|\bat \d{1,2}(:\d{2})? ?(am|pm)?\b"
        ),
    ),
    "ui": Group(
        ("type_text", "click", "press_keys", "read_window_text", "open_app"),
        re.compile(
            r"\b(type|typing|write|click|tap|press|hit|keys?|shortcut|ctrl|control|alt|button|"
            r"menu|window says|what does .{1,40}? say|read (the |that )?.{0,30}window|in notepad|"
            r"into notepad)\b"
        ),
    ),
    "sites": Group(
        ("search_site", "open_url", "browser_open"),
        re.compile(
            r"\b(youtube|yt|wikipedia|wiki|amazon|flipkart|github|reddit|google maps|maps|"
            r"stack ?overflow|spotify|twitter|linkedin|imdb|netflix|pypi|npm|hugging ?face|"
            r"swiggy|zomato|duckduckgo)\b"
        ),
    ),
    "browser": Group(
        ("browser_open", "browser_read", "browser_click", "browser_type", "web_search"),
        re.compile(
            r"\b(fill|form|sign up|add to cart|cart|checkout|book|log ?in to|"
            r"in (the|your|jarvis'?s?) browser|on (the )?(site|website|page)|"
            r"search (it|on|for .+ on) \w*)\b"  # site names are the "sites" group
        ),
    ),
    "messaging": Group(
        ("send_whatsapp",),
        re.compile(
            r"\b(whats ?app|message|messages|msg|text \w+ (that|saying)|tell \w+ (that|to)|"
            r"let \w+ know|send .+ to \w+|reply to)\b"
        ),
    ),
    "calls": Group(
        ("call_contact",),
        re.compile(r"\b(call|phone|dial|ring)\b(?! (me|him|her|them) (back|later))"),
    ),
    "notifications": Group(
        ("read_notifications",),
        re.compile(
            r"\b(notifications?|alerts?|unread|new (\w+ )?messages?|"
            r"any (new )?(\w+ )?(messages?|texts?)|"
            r"anything (new )?from|messages? from|did (anyone|anybody|somebody|\w+) "
            r"(message|text|write|reply|call)|what did \w+ (say|send|write))\b"
        ),
    ),
    "media": Group(
        ("media_control", "now_playing", "set_volume"),
        re.compile(
            r"\b(music|songs?|tracks?|playing|playlist|pause|paused|resume|unpause|play|skip|"
            r"podcast|playback|spotify|album|artist|who sings)\b"
        ),
    ),
    "memory": Group(
        ("remember", "list_memories", "forget"),
        re.compile(
            r"\b(remember|forget|memory|memories|keep in mind|what do you know about me|"
            r"note that)\b"
        ),
    ),
    "speech": Group(
        ("speak",),
        re.compile(r"\b(say|announce|aloud|out loud|read out|pronounce)\b"),
    ),
    "questions": Group(
        ("web_search", "fetch_page"),
        re.compile(r"\b(who|what|when|where|why|how|score)\b"),
        fallback=True,
    ),
}


def matched_groups(text: str) -> list[str]:
    """Names of the groups a request is about (fallback groups only when nothing else matched)."""
    lowered = text.casefold()
    matched = [name for name, group in GROUPS.items() if group.pattern.search(lowered)]
    specific = [name for name in matched if not GROUPS[name].fallback]
    return specific or matched


def select_tools(text: str, registry: Registry) -> list[Tool]:
    lowered = text.casefold()
    matched = [group for group in GROUPS.values() if group.pattern.search(lowered)]
    specific = [group for group in matched if not group.fallback]
    chosen = specific or matched
    if not chosen:
        return list(registry)
    wanted = {name for group in chosen for name in group.tools}
    wanted.update(ALWAYS)
    return [tool for tool in registry if tool.name in wanted]
