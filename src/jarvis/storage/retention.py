"""Old commands and audit rows are deleted on a schedule, so nothing is kept forever by default
(ADR-075, RISKS.md R50). Runs while chat, voice, or the web UI is open."""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta

from jarvis.config import HistorySettings
from jarvis.storage.db import Database

log = logging.getLogger(__name__)

EVERY_S = 24 * 3600


def expire(db: Database, settings: HistorySettings, now: datetime) -> dict[str, int]:
    """Delete what is past its keep time and say how many rows went from each table."""
    gone = {"command_history": 0, "audit_log": 0, "reminders": 0}
    with db.transaction() as conn:
        if settings.keep_days:
            moment = now - timedelta(days=settings.keep_days)
            cutoff = moment.astimezone(UTC).isoformat(timespec="milliseconds")
            gone["command_history"] = conn.execute(
                "DELETE FROM command_history WHERE ts < ?", (cutoff,)
            ).rowcount
            conn.execute(
                "DELETE FROM embeddings WHERE kind = 'history' "
                "AND ref_id NOT IN (SELECT id FROM command_history)"
            )
            gone["reminders"] = conn.execute(
                "DELETE FROM reminders WHERE status != 'pending' AND fired_at < ?",
                (moment.timestamp(),),
            ).rowcount
        if settings.audit_keep_days:
            moment = now - timedelta(days=settings.audit_keep_days)
            cutoff = moment.astimezone(UTC).isoformat(timespec="milliseconds")
            gone["audit_log"] = conn.execute(
                "DELETE FROM audit_log WHERE ts < ?", (cutoff,)
            ).rowcount
    return gone


async def run_retention(db: Database, settings: HistorySettings) -> None:
    while True:
        try:
            gone = expire(db, settings, datetime.now(UTC))
            if any(gone.values()):
                log.info("Deleted old rows: %s", gone)
        except Exception:
            log.exception("Deleting old history failed")
        await asyncio.sleep(EVERY_S)
