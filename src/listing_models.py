from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Listing:
    post_url: str
    group_name: str
    raw_text: str
    price: int | None = None
    rooms: float | None = None
    neighborhoods_mentioned: list[str] = field(default_factory=list)
    roommates: int | None = None
    toilets: int | None = None
    separate_toilet_shower: bool = False
    # How many rooms/spots this POST is currently offering for rent — distinct
    # from `rooms` (the apartment's total size). None when it can't be
    # determined.
    available_rooms: int | None = None
    # The free-text address/area as written in the post (distinct from
    # neighborhoods_mentioned, which is only the matched-keyword subset).
    address: str | None = None
    # Normalized Israeli mobile, "05X-XXXXXXX", or the raw contact text if
    # it doesn't look like one.
    phone: str | None = None
    # Post image URLs, for sending as a Telegram photo/album.
    images: list[str] = field(default_factory=list)
    # A one-line human summary — the LLM's summary when available, else a
    # trimmed excerpt of raw_text.
    summary: str | None = None
    # Filled in by geocoding + zone scoring (src/geocode.py, src/zones.py).
    lat: float | None = None
    lon: float | None = None
    distance_m: float | None = None
    # Filled in by src/scoring.py.
    score: int | None = None
    # Lease timing, as extracted from the post (whatever combination it
    # stated — a date range, a start date + duration, or a bare duration).
    # listing_filters._resolve_dates fills in lease_duration_days from
    # whichever of these was actually extracted, and is the single source
    # of truth for both the min-stay and search-window checks.
    lease_start_date: date | None = None
    lease_end_date: date | None = None
    lease_duration_days: int | None = None
