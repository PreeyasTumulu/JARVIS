"""The tools Jarvis exposes to the model. Add new tools here."""

from __future__ import annotations

from jarvis.tools.apps.docker import docker_list, docker_logs, docker_start, docker_stop
from jarvis.tools.apps.docker_up import docker_up
from jarvis.tools.apps.tools import close_app, focus_app, open_app, schedule_app
from jarvis.tools.apps.vscode import vscode_open
from jarvis.tools.briefing import briefing
from jarvis.tools.browser.tools import browser_click, browser_open, browser_read, browser_type
from jarvis.tools.calendar.tools import calendar_events
from jarvis.tools.data.crypto import crypto_price
from jarvis.tools.data.currency import convert_currency
from jarvis.tools.data.market import market_data
from jarvis.tools.data.weather import weather
from jarvis.tools.dev.git import git_changes, git_commit, git_push
from jarvis.tools.dev.ssh import ssh_connect
from jarvis.tools.files.tools import find_file, get_selected_file, open_file, read_file
from jarvis.tools.interaction import ask_user, speak
from jarvis.tools.mail.tools import read_email, read_mail, reply_email
from jarvis.tools.media.spotify import play_spotify
from jarvis.tools.memory import forget, list_memories, remember
from jarvis.tools.messaging.calls import call_contact, hang_up
from jarvis.tools.messaging.tools import send_whatsapp
from jarvis.tools.news import ai_news
from jarvis.tools.notes import open_notes, read_notes, take_note
from jarvis.tools.notifications.tools import read_notifications
from jarvis.tools.office.calculator import calculator_show
from jarvis.tools.office.sheets import add_sheet_row
from jarvis.tools.recall import forget_history, recall
from jarvis.tools.registry import Registry
from jarvis.tools.system.arithmetic import calculate
from jarvis.tools.system.clipboard import (
    clipboard_forget,
    clipboard_history,
    clipboard_read,
    clipboard_restore,
    clipboard_write,
)
from jarvis.tools.system.controls import lock_screen, screenshot, set_brightness, set_volume
from jarvis.tools.system.focus import focus_end, focus_start, focus_status
from jarvis.tools.system.media import media_control, now_playing
from jarvis.tools.system.reminders import (
    cancel_reminder,
    list_reminders,
    set_reminder,
    set_timer,
)
from jarvis.tools.ui.tools import click, press_keys, read_screen, read_window_text, type_text
from jarvis.tools.vision import look_at_screen
from jarvis.tools.web.browser import open_url
from jarvis.tools.web.fetch import fetch_page
from jarvis.tools.web.search import web_search
from jarvis.tools.web.sites import search_site


def build_registry() -> Registry:
    return Registry(
        [
            open_app,
            focus_app,
            close_app,
            schedule_app,
            take_note,
            read_notes,
            open_notes,
            add_sheet_row,
            calculator_show,
            find_file,
            open_file,
            read_file,
            get_selected_file,
            vscode_open,
            docker_list,
            docker_logs,
            docker_start,
            docker_stop,
            docker_up,
            git_changes,
            git_commit,
            git_push,
            ssh_connect,
            play_spotify,
            look_at_screen,
            ai_news,
            web_search,
            search_site,
            open_url,
            fetch_page,
            market_data,
            crypto_price,
            convert_currency,
            weather,
            set_volume,
            set_brightness,
            media_control,
            now_playing,
            lock_screen,
            screenshot,
            clipboard_read,
            clipboard_write,
            clipboard_history,
            clipboard_restore,
            clipboard_forget,
            focus_start,
            focus_end,
            focus_status,
            calculate,
            set_timer,
            set_reminder,
            list_reminders,
            cancel_reminder,
            type_text,
            click,
            press_keys,
            read_window_text,
            read_screen,
            browser_open,
            browser_read,
            browser_click,
            browser_type,
            send_whatsapp,
            call_contact,
            hang_up,
            read_notifications,
            read_mail,
            read_email,
            reply_email,
            calendar_events,
            remember,
            list_memories,
            forget,
            recall,
            forget_history,
            briefing,
            speak,
            ask_user,
        ]
    )
