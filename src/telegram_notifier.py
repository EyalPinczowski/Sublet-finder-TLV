from __future__ import annotations

import re

import requests

from . import store
from .config import SearchConfig
from .listing_models import Listing
from .scoring import stars

EXCERPT_LIMIT = 300

# A shared Session reuses one keep-alive TCP/TLS connection to
# api.telegram.org across every alert sent this process, instead of each
# _post() call paying a fresh handshake — a scan can send several calls
# per matched listing (photo/album + a follow-up keyboard message).
_session = requests.Session()


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


def format_alert(listing: Listing, profile: SearchConfig, score: int) -> str:
    # The emoji is this profile's "color" — Telegram messages can't carry
    # literal text color, so a distinct emoji per profile (see config.yaml's
    # searches: list) is what makes two profiles' alerts visually distinct
    # from each other at a glance.
    header = f"{profile.emoji} New sublet match — {profile.name} ({listing.group_name})"
    header += f"  {stars(score)} ({score})"
    lines = [header]

    summary = listing.summary or listing.raw_text.strip().replace("\n", " ")
    if len(summary) > EXCERPT_LIMIT:
        summary = summary[:EXCERPT_LIMIT] + "…"
    lines.append(summary)
    lines.append("")

    # A missing price still shows explicitly — an otherwise-matching listing
    # with no stated price reads very differently from one where the price
    # just wasn't mentioned in the alert.
    if listing.price is not None:
        lines.append(f"\U0001F4B0 {listing.price} ILS")
    else:
        lines.append("\U0001F4B0 Price not listed")
    if listing.rooms is not None:
        lines.append(f"\U0001F6CF️ {listing.rooms} rooms")
    if listing.roommates is not None:
        lines.append(f"\U0001F465 {listing.roommates} roommates")
    if listing.toilets is not None:
        lines.append(f"\U0001F6BF {listing.toilets} bathrooms")
    if listing.available_rooms is not None:
        lines.append(f"\U0001F6AA {listing.available_rooms} room(s) available now")
    if listing.lease_start_date is not None:
        lines.append(f"\U0001F4C5 from {listing.lease_start_date.isoformat()}")
    if listing.lease_duration_days is not None:
        lines.append(f"⏳ {listing.lease_duration_days} days")

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


def send_text(bot_token: str, chat_id: str, text: str) -> bool:
    """A plain text message with no photo/keyboard — used for the scan
    heartbeat (see cli.py) and anywhere else that just needs a line of
    text sent to the chat."""
    resp = _post(bot_token, "sendMessage", {"chat_id": chat_id, "text": text}, 15)
    return bool(resp and resp.get("ok"))


def _post(bot_token: str, method: str, payload: dict, timeout: int) -> dict | None:
    try:
        r = _session.post(
            f"https://api.telegram.org/bot{bot_token}/{method}", json=payload, timeout=timeout
        )
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        print(f"[telegram_notifier] {method} failed: {exc}")
        return None


def send_listing(
    bot_token: str, chat_id: str, listing: Listing, profile: SearchConfig, score: int, conn=None
) -> bool:
    """Send one listing alert for one matched profile: an album if it has
    2+ photos, a single photo if it has one, else plain text — each falling
    back to plain text if it fails, so the alert always gets through.

    Called once per profile a listing matched (see cli.py), each with that
    profile's own score — a listing can score very differently under two
    profiles with different price ranges, so the score isn't computed once
    and reused."""
    text = format_alert(listing, profile, score)
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
