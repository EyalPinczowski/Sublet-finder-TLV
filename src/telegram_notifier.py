from __future__ import annotations

import re

import requests

from . import store
from .listing_models import Listing
from .scoring import stars

EXCERPT_LIMIT = 300


def _contact_link(phone: str | None) -> str | None:
    """A tappable WhatsApp link for a normalized Israeli mobile
    ("05X-XXXXXXX"), else None."""
    if not phone:
        return None
    digits = re.sub(r"\D", "", phone)
    if len(digits) == 10 and digits.startswith("05"):
        return "https://wa.me/972" + digits[1:]
    return None


def _map_url(listing: Listing) -> str | None:
    if listing.address:
        from urllib.parse import quote

        return "https://www.google.com/maps/search/?api=1&query=" + quote(
            f"{listing.address}, Tel Aviv"
        )
    if listing.lat is not None and listing.lon is not None:
        return f"https://www.google.com/maps?q={listing.lat},{listing.lon}"
    return None


def format_alert(listing: Listing) -> str:
    header = f"\U0001F3E0 New sublet match ({listing.group_name})"
    if listing.score is not None:
        header += f"  {stars(listing.score)} ({listing.score})"
    lines = [header]

    summary = listing.summary or listing.raw_text.strip().replace("\n", " ")
    if len(summary) > EXCERPT_LIMIT:
        summary = summary[:EXCERPT_LIMIT] + "…"
    lines.append(summary)
    lines.append("")

    if listing.price is not None:
        lines.append(f"\U0001F4B0 {listing.price} ILS/month")
    if listing.rooms is not None:
        lines.append(f"\U0001F6CF️ {listing.rooms} rooms")
    if listing.roommates is not None:
        lines.append(f"\U0001F465 {listing.roommates} roommates")
    if listing.toilets is not None:
        lines.append(f"\U0001F6BF {listing.toilets} bathrooms")

    address = listing.address or (
        ", ".join(listing.neighborhoods_mentioned) if listing.neighborhoods_mentioned else None
    )
    lines.append(f"\U0001F4CD {address or 'address not listed'}")
    if listing.distance_m is not None:
        lines.append(f"   ({listing.distance_m:.0f}m from target zone)")

    if listing.phone:
        lines.append(f"\U0001F4DE {listing.phone}")

    if listing.post_url and listing.post_url.startswith("http"):
        lines.append(f"\U0001F517 {listing.post_url}")

    map_url = _map_url(listing)
    if map_url:
        lines.append(f"\U0001F5FA️ {map_url}")

    wa = _contact_link(listing.phone)
    if wa:
        lines.append(f"\U0001F4AC {wa}")

    return "\n".join(lines)


def _alert_keyboard(conn, post_url: str) -> dict | None:
    if conn is None:
        return None
    try:
        token = store.callback_token(conn, post_url)
    except Exception:
        return None
    return {
        "inline_keyboard": [
            [
                {"text": "⭐ Save", "callback_data": f"save|{token}"},
                {"text": "\U0001F5D1 Dismiss", "callback_data": f"dismiss|{token}"},
            ]
        ]
    }


def _post(bot_token: str, method: str, payload: dict, timeout: int) -> dict | None:
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{bot_token}/{method}", json=payload, timeout=timeout
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"[telegram_notifier] {method} failed: {exc}")
        return None


def send_listing(bot_token: str, chat_id: str, listing: Listing, conn=None) -> bool:
    """Send one listing alert: an album if it has 2+ photos, a single photo
    if it has one, else plain text — each falling back to plain text if it
    fails, so the alert always gets through."""
    text = format_alert(listing)
    keyboard = _alert_keyboard(conn, listing.post_url)
    images = listing.images or []

    if len(images) >= 2:
        media = [{"type": "photo", "media": url} for url in images[:10]]
        media[0]["caption"] = text[:1024]
        resp = _post(
            bot_token,
            "sendMediaGroup",
            {"chat_id": chat_id, "media": media},
            30,
        )
        if resp and resp.get("ok"):
            if keyboard:
                followup = {
                    "chat_id": chat_id,
                    "text": "☝ actions for the listing above:",
                    "reply_markup": keyboard,
                }
                _post(bot_token, "sendMessage", followup, 15)
            return True
    elif len(images) == 1:
        payload = {"chat_id": chat_id, "photo": images[0], "caption": text[:1024]}
        if keyboard:
            payload["reply_markup"] = keyboard
        resp = _post(bot_token, "sendPhoto", payload, 20)
        if resp and resp.get("ok"):
            return True

    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard
    resp = _post(bot_token, "sendMessage", payload, 15)
    return bool(resp and resp.get("ok"))
