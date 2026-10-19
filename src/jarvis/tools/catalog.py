"""The tools Jarvis exposes to the model. Add new tools here."""

from __future__ import annotations

from jarvis.tools.apps.docker import docker_list, docker_logs, docker_start, docker_stop
from jarvis.tools.apps.tools import close_app, focus_app, open_app
from jarvis.tools.apps.vscode import vscode_open
from jarvis.tools.browser.tools import browser_click, browser_open, browser_read, browser_type
from jarvis.tools.data.crypto import crypto_price
from jarvis.tools.data.currency import convert_currency
from jarvis.tools.data.market import market_data
from jarvis.tools.data.weather import weather
from jarvis.tools.files.tools import find_file, get_selected_file, open_file, read_file
from jarvis.tools.interaction import ask_user, speak
from jarvis.tools.memory import forget, list_memories, remember
from jarvis.tools.messaging.tools import send_whatsapp
from jarvis.tools.notifications.tools import read_notifications
from jarvis.tools.registry import Registry
from jarvis.tools.system.clipboard import clipboard_read, clipboard_write
from jarvis.tools.system.controls import lock_screen, screenshot, set_brightness, set_volume
from jarvis.tools.system.reminders import (
    cancel_reminder,
    list_reminders,
    set_reminder,
    set_timer,
)
from jarvis.tools.ui.tools import click, press_keys, read_window_text, type_text
from jarvis.tools.web.browser import open_url
from jarvis.tools.web.fetch import fetch_page
from jarvis.tools.web.search import web_search


def build_registry() -> Registry:
    return Registry(
        [
            open_app,
            focus_app,
            close_app,
            find_file,
            open_file,
            read_file,
            get_selected_file,
            vscode_open,
            docker_list,
            docker_logs,
            docker_start,
            docker_stop,
            web_search,
            open_url,
            fetch_page,
            market_data,
            crypto_price,
            convert_currency,
            weather,
            set_volume,
            set_brightness,
            lock_screen,
            screenshot,
            clipboard_read,
            clipboard_write,
            set_timer,
            set_reminder,
            list_reminders,
            cancel_reminder,
            type_text,
            click,
            press_keys,
            read_window_text,
            browser_open,
            browser_read,
            browser_click,
            browser_type,
            send_whatsapp,
            read_notifications,
            remember,
            list_memories,
            forget,
            speak,
            ask_user,
        ]
    )
