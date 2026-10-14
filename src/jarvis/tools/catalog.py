"""The tools Jarvis exposes to the model. Add new tools here."""

from __future__ import annotations

from jarvis.tools.apps.tools import open_app
from jarvis.tools.interaction import ask_user, speak
from jarvis.tools.registry import Registry
from jarvis.tools.web.search import web_search


def build_registry() -> Registry:
    return Registry([open_app, web_search, speak, ask_user])
