"""Straight-line distance from a geocoded point to a single target point
(e.g. Dizengoff Square) — no walk-time, no routing, just haversine.

config.yaml's zone: block configures the target; ZoneConfig.active is False
when it isn't set, in which case distance_to_target always returns None and
the zone factor in scoring.py/listing_filters.py degrades to "unknown"
rather than failing.
"""
from __future__ import annotations

import math
from typing import Optional

from .config import ZoneConfig

_EARTH_RADIUS_M = 6371000.0


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance between two points, in metres."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return 2 * _EARTH_RADIUS_M * math.asin(math.sqrt(a))


def distance_to_target(lat: float, lon: float, zone: ZoneConfig) -> Optional[float]:
    """Distance in metres from (lat, lon) to the configured zone target, or
    None if no target is configured."""
    if not zone.active:
        return None
    return haversine_m(lat, lon, zone.target_lat, zone.target_lon)


def within_zone(distance_m: Optional[float], zone: ZoneConfig) -> bool:
    """True if a distance is within the configured radius. False (not
    "unknown") when the distance itself is None, so callers that only care
    about the hard-filter path can use this directly; callers that need to
    tell "known and far" apart from "unknown" should check distance_m
    themselves (see scoring.py)."""
    if distance_m is None or not zone.active:
        return False
    return distance_m <= zone.max_distance_meters
