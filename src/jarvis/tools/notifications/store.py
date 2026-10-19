"""Notifications from allowed apps: picked out of the notification center, kept for a few days.

Windows cannot tell an unpackaged process about new notifications, so Jarvis polls the
notification center (every `notifications.poll_s` seconds while it runs, and once more whenever
you ask) and keeps what it has not seen before. Keeping them matters: WhatsApp removes its
notification once you read the message on your phone, so the next poll may not see it again.

Only apps on `notifications.apps` are read past their name and stored. Everything stored is
private, and notification text is written by other people, so it is untrusted data.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from jarvis.config import NotificationsSettings
from jarvis.core.events import EventBus, NotificationsArrived
from jarvis.platform import notifications as platform
from jarvis.platform.notifications import NotificationAccessError, RawNotification
from jarvis.storage.db import Database

log = logging.getLogger(__name__)

# `jarvis notifications test` posts as Windows PowerShell with this title, so you can try the
# feature without allowing PowerShell's other notifications.
TEST_TITLE = "Jarvis test"
ACCESS_RETRY_S = 60


@dataclass(frozen=True)
class Stored:
    id: int
    app: str
    title: str
    body: str
    created: datetime
    read: bool


class NotificationStore:
    def __init__(self, db: Database) -> None:
        self._db = db

    def add(self, items: list[RawNotification], now: datetime) -> list[Stored]:
        """Store the ones not seen before and return them."""
        added: list[Stored] = []
        for item in items:
            rows = self._db.execute(
                """
                INSERT OR IGNORE INTO notifications
                    (win_id, app_id, app, title, body, created_at, seen_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                RETURNING id
                """,
                (
                    item.win_id,
                    item.app_id,
                    item.app,
                    item.title,
                    item.body,
                    item.created.isoformat(),
                    now.isoformat(),
                ),
            )
            if rows:
                added.append(
                    Stored(rows[0][0], item.app, item.title, item.body, item.created, False)
                )
        return added

    def recent(self, *, include_read: bool) -> list[Stored]:
        """Newest first."""
        where = "" if include_read else "WHERE read_at IS NULL"
        rows = self._db.execute(
            f"SELECT id, app, title, body, created_at, read_at FROM notifications {where} "
            "ORDER BY created_at DESC, id DESC"
        )
        return [
            Stored(
                row["id"],
                row["app"],
                row["title"],
                row["body"],
                datetime.fromisoformat(row["created_at"]),
                row["read_at"] is not None,
            )
            for row in rows
        ]

    def mark_read(self, ids: list[int], now: datetime) -> None:
        self._db.executemany(
            "UPDATE notifications SET read_at = ? WHERE id = ? AND read_at IS NULL",
            [(now.isoformat(), item) for item in ids],
        )

    def prune(self, before: datetime) -> None:
        self._db.execute("DELETE FROM notifications WHERE created_at < ?", (before.isoformat(),))

    def keep_only(self, allowed: Callable[[str, str, str], bool]) -> int:
        """Delete what came from apps that are no longer allowed (app, app_id, title)."""
        rows = self._db.execute("SELECT id, app, app_id, title FROM notifications")
        gone = [(r["id"],) for r in rows if not allowed(r["app"], r["app_id"], r["title"])]
        if gone:
            self._db.executemany("DELETE FROM notifications WHERE id = ?", gone)
        return len(gone)


class Notifications:
    """The allowlist, the store, and one refresh at a time."""

    def __init__(
        self,
        db: Database,
        settings: NotificationsSettings,
        *,
        reader: Callable[[], Awaitable[list[RawNotification]]] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = NotificationStore(db)
        self._settings = settings
        self._reader = reader
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = asyncio.Lock()

    def now(self) -> datetime:
        return self._clock()

    def allowed(self, item: RawNotification) -> bool:
        return self._allowed(item.app, item.app_id, item.title)

    def _allowed(self, app: str, app_id: str, title: str) -> bool:
        if app_id == platform.TEST_APP_ID and title.startswith(TEST_TITLE):
            return True
        wanted = {name.casefold() for name in self._settings.apps}
        return app.casefold() in wanted or app_id.casefold() in wanted

    async def refresh(self) -> list[Stored]:
        """Read the notification center once; store and return what is new. Raises
        NotificationAccessError when Windows does not allow reading."""
        async with self._lock:
            # An app taken off notifications.apps takes what was kept from it along, first,
            # so it is gone even when Windows refuses the read below.
            self.store.keep_only(self._allowed)
            read = self._reader or platform.read_all
            now = self.now()
            cutoff = now - timedelta(days=self._settings.keep_days)
            # Old ones still sitting in the notification center must not be stored again.
            items = [i for i in await read() if self.allowed(i) and i.created >= cutoff]
            self.store.prune(cutoff)
            return self.store.add(items, now)


class NotificationWatcher:
    """Polls while Jarvis runs, so notifications that disappear quickly are still kept."""

    def __init__(self, notifications: Notifications, bus: EventBus, poll_s: float) -> None:
        self._notifications = notifications
        self._bus = bus
        self._poll_s = poll_s

    async def run(self) -> None:
        warned = False
        while True:
            try:
                new = await self._notifications.refresh()
            except NotificationAccessError as exc:
                if not warned:
                    log.warning("%s", exc)
                    warned = True
                await asyncio.sleep(ACCESS_RETRY_S)
                continue
            except Exception:
                log.exception("Reading notifications failed")
                await asyncio.sleep(ACCESS_RETRY_S)
                continue
            warned = False
            if new:
                apps = tuple(sorted({item.app for item in new}))
                await self._bus.publish(NotificationsArrived(count=len(new), apps=apps))
            await asyncio.sleep(self._poll_s)
