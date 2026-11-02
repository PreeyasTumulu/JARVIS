"""Old history expires, "forget what I asked" deletes it everywhere, and speech goes quiet on a
locked PC. Windows, the network, and the model are faked."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

from jarvis.config import HistorySettings
from jarvis.core.tool_routing import select_tools
from jarvis.storage.retention import expire
from jarvis.tools.catalog import build_registry
from jarvis.voice.session import LOCKED_NOTICE, VoiceState
from tests.conftest import MakeApp, reply
from tests.unit.test_recall_briefing import call, remember_commands
from tests.unit.test_voice_session import FakeLock, FakeSTT, make_session, push_to_talk, until


def _commands(h: Any) -> list[str]:
    return [row["input_text"] for row in h.app.history.recent(50)]


# Expiry


def _age(h: Any, text: str, days: int) -> None:
    when = (datetime.now(UTC) - timedelta(days=days)).isoformat(timespec="milliseconds")
    h.app.db.execute("UPDATE command_history SET ts = ? WHERE input_text = ?", (when, text))
    h.app.db.execute(
        "INSERT INTO audit_log (ts, session_id, turn_id, tool, decision, ok) "
        "VALUES (?, 's', ?, 'open_app', 'auto', 1)",
        (when, text),
    )


def test_expiry_deletes_only_what_is_past_its_keep_time(make_app: MakeApp) -> None:
    h = make_app()
    remember_commands(h, ("old one", "a"), ("new one", "b"))
    _age(h, "old one", 100)
    _age(h, "new one", 10)
    old_id = h.app.db.execute("SELECT id FROM command_history WHERE input_text = 'old one'")[0][0]
    h.app.db.execute(
        "INSERT INTO embeddings (kind, ref_id, model, vector) VALUES ('history', ?, 'm', x'00')",
        (old_id,),
    )

    gone = expire(h.app.db, HistorySettings(keep_days=90, audit_keep_days=50), datetime.now(UTC))

    assert _commands(h) == ["new one"]
    assert gone == {"command_history": 1, "audit_log": 1, "reminders": 0}
    assert h.app.db.execute("SELECT COUNT(*) FROM embeddings")[0][0] == 0
    assert [row["turn_id"] for row in h.app.audit.recent()] == ["new one"]


def test_zero_keeps_everything(make_app: MakeApp) -> None:
    h = make_app()
    remember_commands(h, ("ancient", "a"))
    _age(h, "ancient", 5000)
    settings = HistorySettings(keep_days=0, audit_keep_days=0)
    assert not any(expire(h.app.db, settings, datetime.now(UTC)).values())
    assert _commands(h) == ["ancient"]


def test_finished_reminders_expire_and_pending_ones_stay(make_app: MakeApp) -> None:
    h = make_app()
    now = datetime.now(UTC)
    old = (now - timedelta(days=100)).timestamp()
    h.app.db.execute(
        "INSERT INTO reminders (kind, message, due_at, created_at, status, fired_at) VALUES "
        "('reminder', 'done long ago', ?, ?, 'done', ?), "
        "('reminder', 'still waiting', ?, ?, 'pending', NULL)",
        (old, old, old, now.timestamp() + 60, old),
    )
    expire(h.app.db, HistorySettings(), now)
    assert [row["message"] for row in h.app.db.execute("SELECT message FROM reminders")] == [
        "still waiting"
    ]


# Forgetting


async def test_forgetting_by_a_word_deletes_commands_vectors_and_audit_rows(
    make_app: MakeApp,
) -> None:
    h = make_app()
    remember_commands(h, ("my doctor appointment", "Tuesday"), ("open notepad", "Opened"))
    doctor_id = h.app.db.execute("SELECT id FROM command_history WHERE turn_id = 't0'")[0][0]
    h.app.db.execute(
        "INSERT INTO embeddings (kind, ref_id, model, vector) VALUES ('history', ?, 'm', x'00')",
        (doctor_id,),
    )
    h.app.db.execute(
        "INSERT INTO audit_log (ts, session_id, turn_id, tool, decision, ok) "
        "VALUES ('2026', 's', 't0', 'read_file', 'auto', 1)"
    )

    outcome = await call(h, "forget_history", about="my doctor")

    assert outcome.result.ok
    assert h.channel.requests[0].summary.startswith('Delete 1 past command (ever), such as "my')
    assert _commands(h) == ["open notepad"]
    assert h.app.db.execute("SELECT COUNT(*) FROM embeddings")[0][0] == 0
    assert not h.app.db.execute("SELECT 1 FROM audit_log WHERE turn_id = 't0'")


async def test_a_word_in_the_answer_counts_and_every_word_must_match(make_app: MakeApp) -> None:
    h = make_app()
    remember_commands(h, ("who called", "Your doctor called"), ("doctor who", "A TV show"))
    outcome = await call(h, "forget_history", about="doctor called")
    assert outcome.result.ok
    assert _commands(h) == ["doctor who"]


async def test_saying_no_deletes_nothing(make_app: MakeApp) -> None:
    from tests.conftest import FakeChannel

    h = make_app(channel=FakeChannel(confirm=False))
    remember_commands(h, ("secret plan", "ok"))
    outcome = await call(h, "forget_history", about="everything")
    assert not outcome.result.ok
    assert _commands(h) == ["secret plan"]


@pytest.mark.parametrize(
    ("args", "error"),
    [
        ({}, "what to delete"),
        ({"about": "the"}, "which words"),
        ({"about": "nothing like this"}, "no past commands"),
        ({"when": "the other day"}, "don't understand the time"),
    ],
)
async def test_vague_requests_delete_nothing(
    make_app: MakeApp, args: dict[str, str], error: str
) -> None:
    h = make_app()
    remember_commands(h, ("open notepad", "Opened"))
    outcome = await call(h, "forget_history", **args)
    assert error in str(outcome.result.error)
    assert _commands(h) == ["open notepad"]


async def test_a_model_cannot_pass_ids_of_its_own(make_app: MakeApp) -> None:
    h = make_app()
    remember_commands(h, ("open notepad", "Opened"))
    outcome = await call(h, "forget_history", about="id:1")
    assert not outcome.result.ok
    assert _commands(h) == ["open notepad"]


async def test_the_conversation_forgets_too_and_the_request_is_not_kept(make_app: MakeApp) -> None:
    h = make_app(
        [
            reply("Tuesday at nine."),
            reply("", ("forget_history", {"about": "doctor"})),
            reply("Done."),
        ]
    )
    await h.app.agent.run_turn("when is my doctor appointment")
    result = await h.app.agent.run_turn("forget what I asked about my doctor")
    assert result.text == "Done."
    assert _commands(h) == []
    assert "appointment" not in json.dumps(h.app.agent.messages)


@pytest.mark.parametrize(
    "text",
    [
        "forget what I asked about docker",
        "delete yesterday's commands",
        "clear my history",
        "erase what I said this morning",
    ],
)
def test_only_the_right_tool_is_offered(text: str) -> None:
    names = {tool.name for tool in select_tools(text, build_registry())}
    assert "forget_history" in names
    assert "recall" not in names
    assert "forget" not in names


def test_forgetting_a_memory_still_offers_forget() -> None:
    names = {t.name for t in select_tools("forget that my manager is Ravi", build_registry())}
    assert "forget" in names
    assert "forget_history" not in names


# Speech on a locked PC


@pytest.fixture
def fast_lock_checks(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("jarvis.voice.session.LOCK_CHECK_S", 0.01)


async def test_a_reminder_while_locked_keeps_its_words_until_unlocking(make_app: MakeApp) -> None:
    h = make_app()
    session, _, _, tts = make_session(h, FakeSTT())
    await session.set_locked(True)

    await session.announce("Reminder: call the doctor.")
    assert tts.spoken == [LOCKED_NOTICE]

    await session.set_locked(False)
    await until(lambda: "Reminder: call the doctor." in tts.spoken)
    assert tts.spoken == [LOCKED_NOTICE, "Reminder: call the doctor."]


async def test_locking_again_keeps_what_was_held(make_app: MakeApp) -> None:
    h = make_app()
    session, _, _, tts = make_session(h, FakeSTT())
    await session.set_locked(True)
    await session.announce("first")
    await session.announce("second")
    assert tts.spoken == [LOCKED_NOTICE, LOCKED_NOTICE]
    await session.set_locked(False)
    await until(lambda: tts.spoken[-1] == "second")
    assert tts.spoken[2:] == ["first", "second"]


async def test_only_the_newest_held_announcements_are_kept(make_app: MakeApp) -> None:
    h = make_app()
    session, _, _, tts = make_session(h, FakeSTT())
    await session.set_locked(True)
    for number in range(15):
        await session.announce(f"item {number}")
    tts.spoken.clear()
    await session.set_locked(False)
    await until(lambda: "item 14" in tts.spoken)
    assert tts.spoken[0] == "item 5"


async def test_an_answer_that_arrives_while_locked_is_not_said(make_app: MakeApp) -> None:
    h = make_app([reply("Your balance is fine.")])
    session, mic, _, tts = make_session(h, FakeSTT("how much money do I have"))
    await push_to_talk(session, mic)
    await session.set_locked(True)
    await until(lambda: not h.app.agent.busy and session.state is VoiceState.MUTED)
    await asyncio.sleep(0.05)
    assert "Your balance is fine." not in tts.spoken


async def test_locking_cuts_off_speech_in_progress(make_app: MakeApp) -> None:
    from tests.unit.test_voice_session import BlockingTTS

    h = make_app()
    blocking = BlockingTTS()
    session, _, _, _ = make_session(h, FakeSTT(), tts=blocking)
    speaking = asyncio.create_task(session.announce("something long and private"))
    await until(lambda: session.state is VoiceState.SPEAKING)
    await session.set_locked(True)
    await asyncio.wait_for(speaking, 1)
    assert blocking.stopped.is_set()


async def test_the_speak_tool_refuses_while_locked(make_app: MakeApp) -> None:
    h = make_app()
    h.app.services.quiet_speech = True
    outcome = await call(h, "speak", text="the secret")
    assert "locked" in str(outcome.result.error)
    assert h.tts.spoken == []


@pytest.mark.usefixtures("fast_lock_checks")
async def test_the_session_tells_the_tools_about_the_lock(make_app: MakeApp) -> None:
    h = make_app()
    lock = FakeLock()
    seen: list[bool] = []
    session, _, _, _ = make_session(h, FakeSTT(), is_locked=lock)
    session._on_locked = seen.append
    runner = asyncio.create_task(session.run())
    try:
        await until(lambda: session.state is VoiceState.IDLE)
        lock.locked = True
        await until(lambda: seen == [True])
        lock.locked = False
        await until(lambda: seen == [True, False])
    finally:
        runner.cancel()
        await asyncio.gather(runner, return_exceptions=True)
