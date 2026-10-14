"""The tools Jarvis exposes to the model. Add new tools here."""

from __future__ import annotations

from jarvis.tools.apps.docker import docker_list, docker_logs, docker_start, docker_stop
from jarvis.tools.apps.tools import close_app, focus_app, open_app
from jarvis.tools.apps.vscode import vscode_open
from jarvis.tools.files.tools import find_file, get_selected_file, open_file, read_file
from jarvis.tools.interaction import ask_user, speak
from jarvis.tools.registry import Registry
from jarvis.tools.web.browser import open_url
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
            speak,
            ask_user,
        ]
    )
