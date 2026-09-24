"""Optional Google Sheets sink: mirror every matched listing into a shared
Sheet you can sort/filter by hand. Additive to SQLite — a no-op whenever
GOOGLE_SHEET_ID isn't set (read lazily here, not at import time, so an
unset var just skips quietly like the rest of this tool's optional pieces).

Setup: see README "Google Sheets".
"""
from __future__ import annotations

import os
from pathlib import Path

from .contact import PRICE_INQUIRY_MESSAGE, whatsapp_link
from .geocode import map_url
from .listing_models import Listing

SERVICE_ACCOUNT_PATH = (
    Path(__file__).resolve().parent.parent / "auth" / "google_service_account.json"
)
HEADER = [
    "post_url", "group", "price", "potential", "rooms", "roommates", "toilets",
    "suitable_for", "address", "phone", "whatsapp", "maps", "lease_start", "stay_days",
    "distance_m", "score", "summary",
]
SCORE_COLUMN = HEADER.index("score") + 1  # 1-based, for Worksheet.sort()


def _suitable_for(available_rooms: int | None) -> str:
    if available_rooms is None:
        return ""
    if available_rooms == 1:
        return "1 person"
    return f"{available_rooms} people"


def _price_cell(price: int | None) -> str | int:
    return price if price is not None else "not listed"


def _potential_cell(price: int | None) -> str:
    # Price is a soft filter — a listing with no stated price still shows
    # up here, but was never actually confirmed to be in budget.
    return "yes" if price is None else ""


def _hyperlink_cell(url: str | None, label: str) -> str:
    """A =HYPERLINK() formula cell — only actually evaluated as a formula
    (rather than inserted as literal "=HYPERLINK(...)" text) because
    save_listing()'s append_row() call passes value_input_option=
    "USER_ENTERED". Doubling an embedded quote is Sheets' own escaping
    rule for a quoted formula argument."""
    if not url:
        return ""
    escaped_url = url.replace('"', '""')
    escaped_label = label.replace('"', '""')
    return f'=HYPERLINK("{escaped_url}", "{escaped_label}")'


def _whatsapp_cell(listing: Listing) -> str:
    # Pre-filled price inquiry when the price is still unknown (a
    # "potential match" is unverified precisely because of that), a
    # plain "open the chat" link otherwise — same rule as the Telegram
    # alert's WhatsApp button and the dashboard card's link.
    message = PRICE_INQUIRY_MESSAGE if listing.price is None else None
    label = "Ask about price" if listing.price is None else "Contact via WhatsApp"
    return _hyperlink_cell(whatsapp_link(listing.phone, message=message), label)


def _maps_cell(listing: Listing) -> str:
    return _hyperlink_cell(map_url(listing.address, listing.lat, listing.lon), "Google Maps")


_sheet = None
_checked = False
# Loaded once per process (inside _get_sheet(), gated by _checked) rather
# than re-fetched via sheet.col_values(1) on every save_listing() call — a
# scan with N matched listings used to pay N full-column reads just to
# check for a duplicate URL. Kept in sync in-memory as rows are appended.
_existing_urls: set[str] | None = None
# True once something's actually been appended since the last flush() —
# lets flush() skip a wasted re-sort call when nothing changed this run.
_dirty = False


def _get_sheet():
    global _sheet, _checked, _existing_urls
    if _checked:
        return _sheet
    _checked = True

    sheet_id = os.environ.get("GOOGLE_SHEET_ID")
    if not sheet_id:
        return None
    if not SERVICE_ACCOUNT_PATH.exists():
        print(
            f"[sheets] GOOGLE_SHEET_ID is set but {SERVICE_ACCOUNT_PATH} is "
            "missing — skipping the Sheets sink"
        )
        return None
    try:
        import gspread

        client = gspread.service_account(filename=str(SERVICE_ACCOUNT_PATH))
        sheet = client.open_by_key(sheet_id).sheet1
        # A brand-new Google Sheet isn't truly "empty" to the API — it
        # returns a single row of blank-string cells rather than [], so a
        # bare `not get_all_values()` check never fires and the header is
        # skipped. Check for any actual content instead.
        has_content = any(any(cell.strip() for cell in row) for row in sheet.get_all_values())
        if not has_content:
            sheet.append_row(HEADER)
        _existing_urls = set(sheet.col_values(1))
        _sheet = sheet
    except Exception as exc:
        print(f"[sheets] could not open the sheet: {exc}")
        _sheet = None
    return _sheet


def save_listing(listing: Listing) -> None:
    """Append one row for a matched listing, skipping it if its post_url is
    already in the sheet (checked against an in-memory cache, not a fresh
    API read — see _existing_urls). No-op (and safe to call
    unconditionally) when the sink isn't configured. Does NOT re-sort the
    sheet itself — call flush() once at the end of a scan for that,
    instead of paying a full-range sort after every single listing."""
    global _dirty
    sheet = _get_sheet()
    if sheet is None:
        return
    if listing.post_url in _existing_urls:
        return
    try:
        sheet.append_row(
            [
                listing.post_url,
                listing.group_name,
                _price_cell(listing.price),
                _potential_cell(listing.price),
                listing.rooms,
                listing.roommates,
                listing.toilets,
                _suitable_for(listing.available_rooms),
                listing.address,
                listing.phone,
                _whatsapp_cell(listing),
                _maps_cell(listing),
                listing.lease_start_date.isoformat() if listing.lease_start_date else "",
                listing.lease_duration_days,
                listing.distance_m,
                listing.score,
                listing.summary,
            ],
            # Without this, "=HYPERLINK(...)" cells would be inserted as
            # literal text (Sheets' RAW mode, gspread's own default) rather
            # than evaluated as an actual clickable formula.
            value_input_option="USER_ENTERED",
        )
        _existing_urls.add(listing.post_url)
        _dirty = True
    except Exception as exc:
        print(f"[sheets] could not save listing: {exc}")


def flush() -> None:
    """Re-sorts the sheet once, if anything was actually appended since
    the last flush() — call once at the end of a scan (see cli._scan),
    not after every save_listing() call."""
    global _dirty
    if _sheet is not None and _dirty:
        _resort(_sheet)
    _dirty = False


def _resort(sheet) -> None:
    """Keep the sheet sorted by score, best first, below the header row."""
    try:
        sheet.sort((SCORE_COLUMN, "des"), range=f"A2:{chr(64 + len(HEADER))}{sheet.row_count}")
    except Exception as exc:
        print(f"[sheets] could not re-sort: {exc}")
