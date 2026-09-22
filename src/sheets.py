"""Optional Google Sheets sink: mirror every matched listing into a shared
Sheet you can sort/filter by hand. Additive to SQLite — a no-op whenever
GOOGLE_SHEET_ID isn't set (read lazily here, not at import time, so an
unset var just skips quietly like the rest of this tool's optional pieces).

Setup: see README "Google Sheets".
"""
from __future__ import annotations

import os
from pathlib import Path

from .listing_models import Listing

SERVICE_ACCOUNT_PATH = (
    Path(__file__).resolve().parent.parent / "auth" / "google_service_account.json"
)
HEADER = [
    "post_url", "group", "price", "rooms", "roommates", "toilets",
    "address", "phone", "distance_m", "score", "summary",
]
SCORE_COLUMN = HEADER.index("score") + 1  # 1-based, for Worksheet.sort()

_sheet = None
_checked = False


def _get_sheet():
    global _sheet, _checked
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
        if not sheet.get_all_values():
            sheet.append_row(HEADER)
        _sheet = sheet
    except Exception as exc:
        print(f"[sheets] could not open the sheet: {exc}")
        _sheet = None
    return _sheet


def save_listing(listing: Listing) -> None:
    """Append one row for a matched listing, skipping it if its post_url is
    already in the sheet. No-op (and safe to call unconditionally) when the
    sink isn't configured."""
    sheet = _get_sheet()
    if sheet is None:
        return
    try:
        existing_urls = sheet.col_values(1)
        if listing.post_url in existing_urls:
            return
        sheet.append_row(
            [
                listing.post_url,
                listing.group_name,
                listing.price,
                listing.rooms,
                listing.roommates,
                listing.toilets,
                listing.address,
                listing.phone,
                listing.distance_m,
                listing.score,
                listing.summary,
            ]
        )
        _resort(sheet)
    except Exception as exc:
        print(f"[sheets] could not save listing: {exc}")


def _resort(sheet) -> None:
    """Keep the sheet sorted by score, best first, below the header row."""
    try:
        sheet.sort((SCORE_COLUMN, "des"), range=f"A2:{chr(64 + len(HEADER))}{sheet.row_count}")
    except Exception as exc:
        print(f"[sheets] could not re-sort: {exc}")
