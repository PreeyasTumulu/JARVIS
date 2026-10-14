from __future__ import annotations

from jarvis.tools.apps.index import AppEntry, AppIndex, normalize
from tests.conftest import FakeChannel, FakeSearch, MakeApp, fake_apps, reply


async def test_match_exact_alias_and_fuzzy() -> None:
    index = fake_apps(
        "Notepad", "Visual Studio Code", "Docker Desktop", aliases={"vs code": "Visual Studio Code"}
    )
    assert (await index.match("NOTEPAD")).entry.name == "Notepad"  # type: ignore[union-attr]
    assert (await index.match("vs code")).entry.name == "Visual Studio Code"  # type: ignore[union-attr]
    assert (await index.match("docker")).entry.name == "Docker Desktop"  # type: ignore[union-attr]
    assert (await index.match("zzzz qqq")).entry is None


async def test_tied_names_are_ambiguous_but_clear_winners_are_not() -> None:
    index = fake_apps(
        "Zoom Workplace", "Zoom Rooms", "Visual Studio Code", "Visual Studio Code Insiders"
    )
    assert (await index.match("zoom")).ambiguous
    clear = await index.match("visual studio cod")
    assert not clear.ambiguous
    assert clear.entry is not None
    assert clear.entry.name == "Visual Studio Code"


async def test_broken_source_is_skipped() -> None:
    def broken() -> list[AppEntry]:
        raise OSError("no powershell")

    index = AppIndex(sources=[broken, lambda: [AppEntry("Notepad", "x", "shortcut")]])
    assert list(await index.entries()) == ["notepad"]


def test_normalize() -> None:
    assert normalize("Python 3.12 (64-bit)") == "python 3 12"
    assert normalize("  Notepad++ ") == "notepad++"


async def test_open_app_reports_ambiguity_to_the_model(make_app: MakeApp) -> None:
    h = make_app([reply("", ("open_app", {"name": "zzzz"})), reply("Which app?")])
    await h.app.agent.run_turn("open zzzz")
    (row,) = h.audit()
    assert row["ok"] == 0
    assert "No installed app" in row["error"]


async def test_web_search_empty_is_a_failure(make_app: MakeApp) -> None:
    h = make_app(
        [reply("", ("web_search", {"query": "x"})), reply("Nothing.")], search=FakeSearch([])
    )
    await h.app.agent.run_turn("search x")
    assert h.audit()[0]["error"] == "The search returned no results."


async def test_speak_uses_tts(make_app: MakeApp) -> None:
    h = make_app([reply("", ("speak", {"text": "Hello Preeyas"})), reply("Said it.")])
    await h.app.agent.run_turn("say hello")
    assert h.tts.spoken == ["Hello Preeyas"]


async def test_ask_user_maps_answers(make_app: MakeApp) -> None:
    channel = FakeChannel(answers=["Spotify"])
    h = make_app(
        [
            reply("", ("ask_user", {"question": "Which app?", "options": ["Spotify", "Notepad"]})),
            reply("ok"),
        ],
        channel=channel,
    )
    await h.app.agent.run_turn("open the music thing")
    assert channel.questions == [("Which app?", ["Spotify", "Notepad"])]
    assert h.audit()[0]["result_json"] == '{"answer": "Spotify"}'
