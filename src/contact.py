"""Shared WhatsApp contact-link building — used by telegram_notifier.py,
scripts/dashboard.py, and sheets.py, so a phone number is normalized into
a wa.me link exactly the same way everywhere, and so all three surfaces
agree on the same pre-filled price-inquiry wording."""
from __future__ import annotations

import re
from urllib.parse import quote

PRICE_INQUIRY_MESSAGE = "היי! ראיתי את הפוסט שלך על הדירה בפייסבוק - מה המחיר החודשי?"


def whatsapp_link(phone: str | None, message: str | None = None) -> str | None:
    """A tappable WhatsApp link for a normalized Israeli mobile
    ("05X-XXXXXXX" or similar), else None. `message` pre-fills the chat
    via wa.me's own `text` query param when given — omit it for a plain
    "just open the chat" link."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) != 10 or not digits.startswith("05"):
        return None
    link = "https://wa.me/972" + digits[1:]
    if message:
        link += f"?text={quote(message)}"
    return link
