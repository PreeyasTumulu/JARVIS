"""Phase 7 feasibility spike: can an unpackaged Python process read Windows notifications?

It checks, in order (docs/ROADMAP.md, Phase 7 step 0):

1. Access: `UserNotificationListener.get_access_status()`, and `request_access_async()` only
   when Windows has no answer yet (a "Denied" is sticky; only Settings can undo it).
2. Reading: posts its own test toast and reads it back with `get_notifications_async`.
3. Polling: posts a second toast and measures how fast a poll-and-diff loop sees it.
4. Events: tries to subscribe to `NotificationChanged` (expected to fail without package
   identity).
5. WhatsApp: whether the WhatsApp app's notifications, if any are there, carry readable text.

Privacy: the full text is printed only for the spike's own test toasts. For everything else in
your notification center it prints how many notifications each app has and whether their text
could be read, never titles or messages. The test toasts are removed at the end.

Run (pywinrt is not a Jarvis dependency until the path is chosen):

    uv run --with winrt-runtime --with winrt-Windows.UI.Notifications.Management `
        --with winrt-Windows.UI.Notifications --with winrt-Windows.Foundation `
        --with winrt-Windows.Foundation.Collections --with winrt-Windows.Data.Xml.Dom `
        --with winrt-Windows.ApplicationModel python scripts/spike_notifications.py
"""

from __future__ import annotations

import asyncio
import time
import uuid
from collections import Counter
from typing import Any

from winrt.windows.data.xml.dom import XmlDocument
from winrt.windows.ui.notifications import (
    KnownNotificationBindings,
    NotificationKinds,
    ToastNotification,
    ToastNotificationManager,
)
from winrt.windows.ui.notifications.management import (
    UserNotificationListener,
    UserNotificationListenerAccessStatus,
)

# Windows PowerShell's registered app id: unpackaged code needs a registered id to show a toast.
TEST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"
MARK = f"Jarvis spike {uuid.uuid4().hex[:6]}"
POLL_S = 0.5


def show_toast(title: str, body: str) -> None:
    xml = XmlDocument()
    xml.load_xml(
        "<toast><visual><binding template='ToastGeneric'>"
        f"<text>{title}</text><text>{body}</text>"
        "</binding></visual></toast>"
    )
    create = getattr(ToastNotificationManager, "create_toast_notifier_with_id", None)
    notifier = (
        create(TEST_APP_ID)
        if create
        else ToastNotificationManager.create_toast_notifier(TEST_APP_ID)
    )
    notifier.show(ToastNotification(xml))


def app_name(note: Any) -> str:
    try:
        return str(note.app_info.display_info.display_name) or "(no name)"
    except Exception as exc:  # some Win32 senders have no app info
        return f"(unknown: {type(exc).__name__})"


def texts(note: Any) -> list[str]:
    try:
        binding = note.notification.visual.get_binding(KnownNotificationBindings.toast_generic)
    except Exception:
        return []
    if binding is None:
        return []
    return [str(element.text) for element in binding.get_text_elements()]


async def snapshot(listener: Any) -> list[Any]:
    return list(await listener.get_notifications_async(NotificationKinds.TOAST))


def hresult(exc: BaseException) -> str:
    code = getattr(exc, "winerror", None) or getattr(exc, "hresult", None)
    if isinstance(code, int):
        return f"0x{code & 0xFFFFFFFF:08X}"
    return type(exc).__name__


async def main() -> None:
    listener = UserNotificationListener.current
    status = listener.get_access_status()
    print(f"1. Access status: {status.name}")
    if status == UserNotificationListenerAccessStatus.UNSPECIFIED:
        try:
            status = await listener.request_access_async()
            print(f"   request_access_async: {status.name}")
        except Exception as exc:
            print(f"   request_access_async failed: {hresult(exc)} {exc}")
    if status != UserNotificationListenerAccessStatus.ALLOWED:
        print("   Not allowed. Settings > Privacy & security > Notifications decides this.")
        return

    started = time.perf_counter()
    before = await snapshot(listener)
    took_ms = (time.perf_counter() - started) * 1000
    print(f"2. get_notifications_async: {len(before)} toasts in {took_ms:.0f} ms")
    readable: Counter[str] = Counter()
    per_app: Counter[str] = Counter()
    for note in before:
        name = app_name(note)
        per_app[name] += 1
        readable[name] += bool(any(t.strip() for t in texts(note)))
    for name, count in per_app.most_common():
        print(f"   {name}: {count} (text readable in {readable[name]})")

    show_toast(f"{MARK} A", "First test message from the Jarvis notification spike.")
    ours: list[Any] = []
    for _ in range(20):
        await asyncio.sleep(POLL_S)
        ours = [n for n in await snapshot(listener) if any(MARK in t for t in texts(n))]
        if ours:
            break
    if not ours:
        print("   The spike's own test toast never showed up in get_notifications_async.")
    for note in ours:
        print(f"   Own toast read back: id={note.id} app={app_name(note)!r} text={texts(note)}")

    seen = {n.id for n in await snapshot(listener)}
    show_toast(f"{MARK} B", "Second test message, to time polling.")
    posted = time.perf_counter()
    new: list[Any] = []
    for _ in range(20):
        await asyncio.sleep(POLL_S)
        new = [n for n in await snapshot(listener) if n.id not in seen]
        if new:
            break
    delay = time.perf_counter() - posted
    found = [texts(n) for n in new if any(MARK in t for t in texts(n))]
    print(f"3. Polling every {POLL_S} s: new toast seen after {delay:.1f} s: {found or 'not seen'}")

    try:
        token = listener.add_notification_changed(lambda sender, args: None)
        print(f"4. NotificationChanged subscription worked (token {token})")
        listener.remove_notification_changed(token)
    except Exception as exc:
        print(f"4. NotificationChanged subscription failed: {hresult(exc)} {exc}")

    whatsapp = [n for n in before if "whatsapp" in app_name(n).casefold()]
    if whatsapp:
        lengths = [sum(len(t) for t in texts(n)) for n in whatsapp]
        print(f"5. WhatsApp: {len(whatsapp)} toasts, text characters per toast: {lengths}")
    else:
        print("5. WhatsApp: no WhatsApp notifications in the notification center right now")

    removed = 0
    for note in await snapshot(listener):
        if any(MARK in t for t in texts(note)):
            try:
                listener.remove_notification(note.id)
                removed += 1
            except Exception as exc:
                print(f"   Could not remove test toast {note.id}: {hresult(exc)}")
    print(f"   Removed {removed} test toasts.")


if __name__ == "__main__":
    asyncio.run(main())
