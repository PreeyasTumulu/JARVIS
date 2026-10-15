"""The Windows notification center, read through UserNotificationListener (pywinrt).

Measured in the Phase 7 spike (RISKS.md R4): an unpackaged Python process can read every toast
with its text in tens of milliseconds, but cannot subscribe to the NotificationChanged event
(0x80070490 without package identity), so Jarvis polls. Access is a Windows privacy setting:
Settings > Privacy & security > Notifications.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

# Windows PowerShell's registered app id: unpackaged code needs one to show a toast at all.
TEST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


class NotificationAccessError(Exception):
    """Windows does not let Jarvis read notifications. The message says where to change it."""


@dataclass(frozen=True)
class RawNotification:
    win_id: int  # Windows' id for this notification
    app_id: str  # app user model id, for example 5319275A.WhatsAppDesktop_cv1g1gvanyjgm!App
    app: str  # display name, for example WhatsApp
    title: str  # first text line: for WhatsApp the chat or the sender
    body: str  # the other text lines
    created: datetime  # UTC


def access_status() -> str:
    """The access status name (ALLOWED, DENIED, UNSPECIFIED), without asking."""
    from winrt.windows.ui.notifications.management import UserNotificationListener

    return str(UserNotificationListener.current.get_access_status().name)


async def read_all() -> list[RawNotification]:
    """Every toast in the notification center. Raises NotificationAccessError."""
    from winrt.windows.ui.notifications import NotificationKinds
    from winrt.windows.ui.notifications.management import (
        UserNotificationListener,
        UserNotificationListenerAccessStatus,
    )

    listener = UserNotificationListener.current
    status = listener.get_access_status()
    if status == UserNotificationListenerAccessStatus.UNSPECIFIED:
        status = await listener.request_access_async()
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        raise NotificationAccessError(
            "Windows does not let Jarvis read notifications. Turn on notification access in "
            "Settings > Privacy & security > Notifications."
        )
    return [
        _convert(note) for note in await listener.get_notifications_async(NotificationKinds.TOAST)
    ]


def _convert(note: Any) -> RawNotification:
    lines = _texts(note)
    try:
        app_id = str(note.app_info.app_user_model_id)
        app = str(note.app_info.display_info.display_name)
    except Exception:  # a few senders come without app info
        app_id, app = "", ""
    created = note.creation_time
    if isinstance(created, datetime):
        created = created.astimezone(UTC) if created.tzinfo else created.replace(tzinfo=UTC)
    else:
        created = datetime.now(UTC)
    return RawNotification(
        win_id=int(note.id),
        app_id=app_id,
        app=app,
        title=lines[0] if lines else "",
        body="\n".join(lines[1:]),
        created=created,
    )


def _texts(note: Any) -> list[str]:
    from winrt.windows.ui.notifications import KnownNotificationBindings

    try:
        binding = note.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
    except Exception:
        return []
    if binding is None:
        return []
    return [str(element.text).strip() for element in binding.get_text_elements()]


def show_toast(title: str, body: str) -> None:
    """Show a toast (as Windows PowerShell). Used by `jarvis notifications test`."""
    from xml.sax.saxutils import escape

    from winrt.windows.data.xml.dom import XmlDocument
    from winrt.windows.ui.notifications import ToastNotification, ToastNotificationManager

    xml = XmlDocument()
    xml.load_xml(
        "<toast><visual><binding template='ToastGeneric'>"
        f"<text>{escape(title)}</text><text>{escape(body)}</text>"
        "</binding></visual></toast>"
    )
    ToastNotificationManager.create_toast_notifier_with_id(TEST_APP_ID).show(ToastNotification(xml))
