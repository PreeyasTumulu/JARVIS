"""WhatsApp Web page selectors, kept in one place because WhatsApp changes its page without notice.

When sending breaks after a WhatsApp update, this is the file to fix (RISKS.md R5). Each entry
lists a few alternatives, newest first. They were written against WhatsApp Web as of late 2026
and the fake page in tests/fixtures/whatsapp_web.html; check them against the real page with
`uv run jarvis whatsapp login` and the browser's developer tools (F12).
"""

from __future__ import annotations

import re

# Shown when this profile is not linked to a phone.
QR_CODE = "canvas[aria-label*='scan' i], div[data-ref] canvas, [data-testid='qrcode']"
# The chat list: present once WhatsApp Web is linked and loaded.
CHAT_LIST = "#pane-side, div[aria-label='Chat list' i], [data-testid='chat-list']"
# The message box of the open chat.
COMPOSE = (
    "#main footer div[contenteditable='true'][role='textbox'], "
    "#main footer div[contenteditable='true'], "
    "footer [data-testid='conversation-compose-box-input']"
)
SEND_BUTTON = (
    "#main footer button[aria-label='Send' i], "
    "#main footer [data-icon='wds-ic-send-filled'], "
    "#main footer [data-icon='send']"
)
# The popup for a click-to-chat link whose number has no WhatsApp account.
INVALID_NUMBER = re.compile(r"phone number shared via url is invalid", re.IGNORECASE)
# Messages you sent in the open chat, oldest first, and the parts of one message.
OUTGOING = "#main div.message-out"
MESSAGE_TEXT = "span.selectable-text, [data-testid='selectable-text']"
STATUS_ICON = (
    "[data-icon='msg-time'], [data-icon='msg-check'], [data-icon='msg-dblcheck'], "
    "[data-icon='msg-dblcheck-ack']"
)
