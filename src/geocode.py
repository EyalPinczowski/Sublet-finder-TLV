"""Free geocoding via Nominatim (OpenStreetMap), bounded to Tel Aviv and
cached to disk so the same address is never looked up twice.

No API key, no Docker — just a rate-limited HTTPS call, same free path
bgu-housing-bot falls back to when its paid/self-hosted options are off.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Optional
from urllib.parse import quote

import requests

CACHE_PATH = Path(__file__).resolve().parent.parent / "data" / "geocode_cache.json"

# lon_left,lat_top,lon_right,lat_bottom — a box around Tel Aviv-Yafo, used
# with bounded=1 so a street name that also exists elsewhere in Israel can't
# geocode outside the city.
TEL_AVIV_VIEWBOX = "34.72,32.15,34.85,32.02"

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
NOMINATIM_USER_AGENT = "sublet-finder-tlv/1.0 (personal apartment search)"

# Nominatim's usage policy caps free use at ~1 request/second.
_MIN_INTERVAL_SEC = 1.0
_last_call = 0.0

# A shared Session reuses one keep-alive TCP/TLS connection to Nominatim
# across every geocode() call this process makes, instead of each call
# paying a fresh handshake.
_session = requests.Session()
_session.headers.update({"User-Agent": NOMINATIM_USER_AGENT})

_cache: Optional[dict] = None


def _load_cache() -> dict:
    global _cache
    if _cache is not None:
        return _cache
    try:
        with open(CACHE_PATH, encoding="utf-8") as f:
            _cache = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        _cache = {}
    return _cache


def _save_cache() -> None:
    if _cache is None:
        return
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CACHE_PATH, "w", encoding="utf-8") as f:
        json.dump(_cache, f, ensure_ascii=False, indent=2)


def _normalize(address: str) -> str:
    return " ".join(address.split()).strip().lower()


def _pace() -> None:
    global _last_call
    gap = _MIN_INTERVAL_SEC - (time.monotonic() - _last_call)
    if gap > 0:
        time.sleep(gap)
    _last_call = time.monotonic()


def map_url(
    address: Optional[str], lat: Optional[float] = None, lon: Optional[float] = None
) -> Optional[str]:
    """A tappable Google Maps link for a listing — from its address when
    known (a search query resolves better for an apartment than raw
    coordinates, e.g. shows the building rather than a mid-street point),
    else its geocoded lat/lon, else None. Shared by telegram_notifier.py
    and dashboard.py so a listing's map link is never computed two
    different ways."""
    if address:
        return "https://www.google.com/maps/search/?api=1&query=" + quote(
            f"{address}, Tel Aviv"
        )
    if lat is not None and lon is not None:
        return f"https://www.google.com/maps?q={lat},{lon}"
    return None


def geocode(address: str) -> Optional[tuple[float, float]]:
    """(lat, lon) for a free-text address in/around Tel Aviv, or None if it
    can't be resolved. Cached — a repeat lookup never hits the network."""
    if not address or not address.strip():
        return None
    key = _normalize(address)
    cache = _load_cache()
    if key in cache:
        cached = cache[key]
        return tuple(cached) if cached else None

    result = _geocode_live(address)
    cache[key] = list(result) if result else None
    _save_cache()
    return result


def _geocode_live(address: str) -> Optional[tuple[float, float]]:
    _pace()
    try:
        resp = _session.get(
            NOMINATIM_URL,
            params={
                "q": f"{address}, Tel Aviv, Israel",
                "format": "json",
                "limit": 1,
                "viewbox": TEL_AVIV_VIEWBOX,
                "bounded": 1,
            },
            timeout=10,
        )
        resp.raise_for_status()
        results = resp.json()
    except Exception:
        return None
    if not results:
        return None
    try:
        return float(results[0]["lat"]), float(results[0]["lon"])
    except (KeyError, ValueError, TypeError):
        return None
