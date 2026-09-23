"""A 0-100 "fit" score for a matched listing, so the best options surface
first instead of an unranked list. Adapted from bgu-housing-bot's fit.py,
but built from scratch around what this tool actually extracts — no
floor/elevator/furnished/balcony/broker factors, since nothing here parses
those. Bathroom count is deliberately excluded too — it's parsed
(`Listing.toilets`) and still shown in alerts, but is neither a match
filter nor a ranking factor; too noisy a signal either way.

Each factor contributes an independent, capped delta; unknown data gets a
neutral (not zero, not full) fill so a listing missing one field is never
penalized as hard as a listing known to be bad on that field. `score()` is
just the clamped sum of `breakdown()`'s deltas — one source of truth, so an
alert's "why this score" line can never drift from the number.
"""
from __future__ import annotations

from typing import Optional

from .config import SearchConfig, ZoneConfig
from .listing_filters import _resolve_dates
from .listing_models import Listing


def _zone_points(listing: Listing, zone_cfg: Optional[ZoneConfig]) -> tuple[str, int]:
    if listing.distance_m is not None:
        d = listing.distance_m
        if d <= 300:
            return f"{d:.0f}m from {zone_cfg.target_label or 'target'}", 25
        if d <= 600:
            return f"{d:.0f}m from {zone_cfg.target_label or 'target'}", 18
        cutoff = zone_cfg.max_distance_meters if zone_cfg else 1000
        if d <= cutoff:
            return f"{d:.0f}m from {zone_cfg.target_label or 'target'}", 10
        return f"{d:.0f}m from {zone_cfg.target_label or 'target'} (far)", 0
    if listing.neighborhoods_mentioned:
        return "neighborhood match", 5
    return "location unknown", 12


def _price_points(
    price: Optional[int], search_cfg: SearchConfig, duration_days: Optional[int] = None
) -> tuple[str, int]:
    if price is None:
        return "price not listed", 12
    lo, hi = search_cfg.price_min, search_cfg.price_max
    if duration_days is not None:
        # Mirror listing_filters.matches()'s proration exactly, so a
        # listing's score is never computed against a different budget
        # than the one that decided whether it matched at all.
        factor = min(duration_days / 30, 1.0)
        lo = lo * factor if lo is not None else None
        hi = hi * factor if hi is not None else None
    if lo is not None and price <= lo:
        return f"{price} ILS (at/below target)", 25
    if lo is not None and hi is not None and hi > lo:
        # Linear taper from 25 at price_min down to 5 at price_max.
        frac = (price - lo) / (hi - lo)
        return f"{price} ILS", round(25 - frac * 20)
    if hi is not None and price <= hi:
        return f"{price} ILS", 18
    return f"{price} ILS", 12


def _rooms_points(rooms: Optional[float], search_cfg: SearchConfig) -> tuple[str, int]:
    if rooms is None:
        return "rooms not listed", 8
    if search_cfg.min_rooms is None:
        return f"{rooms} rooms", 15
    if rooms >= search_cfg.min_rooms:
        return f"{rooms} rooms", 15
    if search_cfg.min_rooms > 0:
        frac = max(0.0, rooms / search_cfg.min_rooms)
        return f"{rooms} rooms", round(15 * frac)
    return f"{rooms} rooms", 8


def _roommates_points(roommates: Optional[int], search_cfg: SearchConfig) -> tuple[str, int]:
    if roommates is None:
        return "roommates not listed", 8
    cap = search_cfg.max_roommates
    if cap is None or cap <= 0:
        return f"{roommates} roommates", 15
    if roommates <= 2:
        return f"{roommates} roommates", 15
    frac = max(0.0, (cap - roommates) / cap)
    return f"{roommates} roommates", round(15 * frac)


def _freshness_points(age_hours: Optional[float]) -> tuple[str, int]:
    if age_hours is None:
        return "age unknown", 5
    days = age_hours / 24
    if days < 1:
        return "posted <1d ago", 10
    if days < 3:
        return "posted <3d ago", 6
    if days < 7:
        return "posted <7d ago", 2
    return "posted 7d+ ago", 0


def breakdown(
    listing: Listing,
    search_cfg: SearchConfig,
    zone_cfg: Optional[ZoneConfig] = None,
    age_hours: Optional[float] = None,
) -> list[tuple[str, int]]:
    """The score's per-factor contributions as [(label, delta), ...], in the
    order they're applied — the single source of truth `score()` sums."""
    _, duration_days = _resolve_dates(listing)
    parts = [
        _zone_points(listing, zone_cfg),
        _price_points(listing.price, search_cfg, duration_days),
        _rooms_points(listing.rooms, search_cfg),
        _roommates_points(listing.roommates, search_cfg),
        _freshness_points(age_hours),
    ]
    if listing.images:
        parts.append(("has photos", 5))
    return parts


def score(
    listing: Listing,
    search_cfg: SearchConfig,
    zone_cfg: Optional[ZoneConfig] = None,
    age_hours: Optional[float] = None,
) -> int:
    total = sum(delta for _, delta in breakdown(listing, search_cfg, zone_cfg, age_hours))
    return max(0, min(100, total))


def stars(score_value: int) -> str:
    """1-5 star rating for a 0-100 score. Strict thresholds so 5 stars
    means genuinely excellent, mirroring bgu's fit.stars()."""
    if score_value >= 85:
        n = 5
    elif score_value >= 70:
        n = 4
    elif score_value >= 55:
        n = 3
    elif score_value >= 35:
        n = 2
    else:
        n = 1
    return "⭐" * n


def top_factors(parts: list[tuple[str, int]], n: int = 3) -> list[tuple[str, int]]:
    """The n highest-scoring factors, for a "why this score" line."""
    return sorted(parts, key=lambda p: p[1], reverse=True)[:n]
