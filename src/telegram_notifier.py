from __future__ import annotations

import requests

from .listing_models import Listing

EXCERPT_LIMIT = 300


def send_listing(bot_token: str, chat_id: str, listing: Listing) -> None:
    lines = [f"\U0001F3E0 New sublet match ({listing.group_name})"]

    if listing.price is not None:
        lines.append(f"\U0001F4B0 {listing.price} ₪/month")
    if listing.rooms is not None:
        lines.append(f"\U0001F6CF️ {listing.rooms} rooms")
    if listing.neighborhoods_mentioned:
        lines.append(f"\U0001F4CD {', '.join(listing.neighborhoods_mentioned)}")
    if listing.post_url:
        lines.append(listing.post_url)

    excerpt = listing.raw_text.strip().replace("\n", " ")
    if len(excerpt) > EXCERPT_LIMIT:
        excerpt = excerpt[:EXCERPT_LIMIT] + "…"

    lines.append("")
    lines.append(excerpt)

    response = requests.post(
        f"https://api.telegram.org/bot{bot_token}/sendMessage",
        json={"chat_id": chat_id, "text": "\n".join(lines)},
        timeout=10,
    )
    response.raise_for_status()
