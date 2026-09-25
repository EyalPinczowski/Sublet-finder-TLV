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
    ("05X-XXXXXXX" or similar) or an already-international number (e.g.
    "+1 619 375 2500" — some posts give a non-Israeli WhatsApp contact),
    else None. `message` pre-fills the chat via wa.me's own `text` query
    param when given — omit it for a plain "just open the chat" link."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10 and digits.startswith("05"):
        # wa.me needs the full international number: 972 country code,
        # no leading 0.
        digits = "972" + digits[1:]
    elif not phone.strip().startswith("+") or len(digits) < 8:
        # Neither a recognized Israeli mobile nor an explicit
        # international number ("+" is what marks a number as already
        # carrying its own country code) — nothing safe to link to.
        return None
    link = "https://wa.me/" + digits
    if message:
        link += f"?text={quote(message)}"
    return link
