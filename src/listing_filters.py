from __future__ import annotations

import re
from datetime import date, timedelta

from .config import SearchConfig, StayConfig, ZoneConfig
from .listing_models import Listing
from .zones import within_zone

# Hebrew final letters revert to their regular form once a suffix is
# added (e.g. מתווך "broker" ends in final-kaf ך, but מתווכת "broker"
# (fem.)/מתווכים (pl.) use regular-kaf כ instead) — so each root needs
# both a "regular-kaf + more letters" branch and a "final-kaf, standalone"
# branch; \w* alone after the final-kaf form would never match the
# inflected ones.
_BROKER_TERM_RE = re.compile(r"(?:תיווכ\w*|תיווך\b|מתווכ\w*|מתווך\b)")
_BROKER_NEGATED_RE = re.compile(
    r"(?:ללא|בלי|אין)\s+(?:תיווכ\w*|תיווך\b|מתווכ\w*|מתווך\b)"
)


def _mentions_broker(raw_text: str) -> bool:
    """True if the post looks like a broker/agency listing. "ללא תיווך"/
    "בלי תיווך"/"אין תיווך" ("no broker fee") is the OPPOSITE signal — a
    direct-from-tenant post advertising that it's NOT brokered — so those
    negated mentions are stripped before checking for a real one."""
    text = raw_text or ""
    stripped = _BROKER_NEGATED_RE.sub("", text)
    return bool(_BROKER_TERM_RE.search(stripped))


# "רק לבנות/לנשים/לבחורות", "בנות/נשים/בחורות בלבד", "דירת בנות", and the
# English equivalents — an explicit exclusivity claim, not just any
# mention of "בנות" (which would false-positive on e.g. "מתאים לבנות
# ולבנים", "suitable for girls and guys"). "לא רק לבנות"/"not girls only"
# is the OPPOSITE signal (explicitly open to everyone) and is stripped
# first, same as the broker filter's "ללא תיווך" handling — otherwise
# "לא רק לבנות" would match "רק לבנות" as a substring and wrongly filter
# out a listing that's actually open to all.
_GIRLS_ONLY_TERM_RE = re.compile(
    r"רק\s+ל(?:בנות|נשים|בחורות)"
    r"|(?:בנות|נשים|בחורות)\s+בלבד"
    r"|דירת\s+בנות"
    r"|(?:girls?|females?|women)\s+only"
    r"|only\s+(?:for\s+)?(?:girls?|females?|women)",
    re.IGNORECASE,
)
_GIRLS_ONLY_NEGATED_RE = re.compile(
    r"לא\s+רק\s+ל(?:בנות|נשים|בחורות)"
    r"|לא\s+(?:בנות|נשים|בחורות)\s+בלבד"
    r"|not\s+(?:girls?|females?|women)\s+only"
    r"|not\s+only\s+(?:for\s+)?(?:girls?|females?|women)",
    re.IGNORECASE,
)


def _mentions_girls_only(raw_text: str) -> bool:
    """True if the post restricts the room/apartment to women/girls only.
    "לא רק לבנות"/"not girls only" is the OPPOSITE signal — explicitly
    open to everyone — so those negated mentions are stripped before
    checking for a real restriction."""
    text = raw_text or ""
    stripped = _GIRLS_ONLY_NEGATED_RE.sub("", text)
    return bool(_GIRLS_ONLY_TERM_RE.search(stripped))


def _resolve_dates(
    listing: Listing, today: date | None = None
) -> tuple[date | None, int | None]:
    """(start_date, duration_days) reconciled from whatever combination of
    lease_start_date/lease_end_date/lease_duration_days was actually
    extracted (a date range, a start date + stated duration, a bare
    duration, or a bare end date) — the single place this logic lives, so
    the LLM and regex extraction paths, this filter, and scoring.py never
    disagree on it."""
    start = listing.lease_start_date
    end = listing.lease_end_date
    duration = listing.lease_duration_days
    if duration is None and start is not None and end is not None:
        duration = (end - start).days
    elif duration is None and start is None and end is not None:
        # An end date with no stated start most naturally reads as
        # "available now, until <end>" — assume today, rather than
        # treating the post as having no date info at all.
        start = today or date.today()
        duration = (end - start).days
    if duration is not None and duration <= 0:
        return start, None  # an end date already in the past isn't usable
    return start, duration


def matches(
    listing: Listing,
    search_cfg: SearchConfig,
    zone_cfg: ZoneConfig | None = None,
    stay_cfg: StayConfig | None = None,
    today: date | None = None,
) -> bool:
    """Full check — still the single source of truth (used directly by
    tests and by --dry-run's per-post evaluation), composed of the two
    phases below so a caller (cli.py's _scan) can run the cheap one first
    and only geocode a listing that has a real chance of matching."""
    return matches_without_location(
        listing, search_cfg, stay_cfg, today
    ) and location_ok(listing, search_cfg, zone_cfg)


def matches_without_location(
    listing: Listing,
    search_cfg: SearchConfig,
    stay_cfg: StayConfig | None = None,
    today: date | None = None,
) -> bool:
    """Everything EXCEPT the neighborhoods/zone-distance check (see
    location_ok) — no geocoding required. Run this first, before
    geocoding a new listing, so one that was always going to fail on
    price/rooms/excluded-keywords/broker/etc. never pays for a lookup."""
    price_min, price_max = search_cfg.price_min, search_cfg.price_max

    if stay_cfg is not None:
        start, duration = _resolve_dates(listing, today=today)
        # Dates are soft-optional, like every other field in this function —
        # a listing with no date/duration info at all still passes (no
        # longer a hard gate; see README "Stay length and dates"). The
        # minimum-stay and search-window checks below still apply whenever
        # that specific piece of info IS known.
        if duration is not None and duration < stay_cfg.min_days:
            return False
        if start is not None:
            window_start = today or date.today()
            window_end = window_start + timedelta(days=stay_cfg.search_window_days)
            if not (window_start <= start <= window_end):
                return False
        if duration is not None:
            # Prorate the monthly budget down for a stay under a month,
            # since listing.price for a short sublet is the TOTAL for its
            # stated period, not a monthly rate. Never prorate UP for a
            # longer stay — normal monthly-rate listings are unaffected.
            # Skipped entirely when duration is unknown — nothing to
            # prorate against.
            factor = min(duration / 30, 1.0)
            if price_min is not None:
                price_min = price_min * factor
            if price_max is not None:
                price_max = price_max * factor

    if price_max is not None and listing.price is not None and listing.price > price_max:
        return False

    if price_min is not None and listing.price is not None and listing.price < price_min:
        return False

    if (
        search_cfg.min_rooms is not None
        and listing.rooms is not None
        and listing.rooms < search_cfg.min_rooms
    ):
        return False

    if (
        search_cfg.min_available_rooms is not None
        and listing.available_rooms is not None
        and listing.available_rooms < search_cfg.min_available_rooms
    ):
        return False

    if (
        search_cfg.max_available_rooms is not None
        and listing.available_rooms is not None
        and listing.available_rooms > search_cfg.max_available_rooms
    ):
        return False

    if search_cfg.excluded_keywords:
        lowered = listing.raw_text.lower()
        if any(k.lower() in lowered for k in search_cfg.excluded_keywords):
            return False

    if _mentions_broker(listing.raw_text):
        return False

    if _mentions_girls_only(listing.raw_text):
        return False

    if (
        search_cfg.max_roommates is not None
        and listing.roommates is not None
        and listing.roommates > search_cfg.max_roommates
    ):
        return False

    return True


def explain_mismatch(
    listing: Listing,
    search_cfg: SearchConfig,
    zone_cfg: ZoneConfig | None = None,
    stay_cfg: StayConfig | None = None,
    today: date | None = None,
) -> list[str]:
    """Every reason matches() would reject this listing against this one
    profile, in the same order matches() checks them — empty list means it
    matches. Diagnostic-only: mirrors matches_without_location()/
    location_ok() but collects every reason instead of short-circuiting on
    the first one, so a "why isn't anything matching" sanity check (see
    cli.py's --explain flag) can show the actual cause rather than a bare
    yes/no. Never used by the scan's real match decision — matches()/
    matches_without_location()/location_ok() stay the single source of
    truth for that."""
    reasons: list[str] = []
    price_min, price_max = search_cfg.price_min, search_cfg.price_max

    if stay_cfg is not None:
        start, duration = _resolve_dates(listing, today=today)
        if duration is not None and duration < stay_cfg.min_days:
            reasons.append(f"stay is {duration} days, need at least {stay_cfg.min_days}")
        if start is not None:
            window_start = today or date.today()
            window_end = window_start + timedelta(days=stay_cfg.search_window_days)
            if not (window_start <= start <= window_end):
                reasons.append(
                    f"lease starts {start.isoformat()}, outside the "
                    f"{stay_cfg.search_window_days}-day search window"
                )
        if duration is not None:
            factor = min(duration / 30, 1.0)
            if price_min is not None:
                price_min = price_min * factor
            if price_max is not None:
                price_max = price_max * factor

    if price_max is not None and listing.price is not None and listing.price > price_max:
        reasons.append(f"price {listing.price} above max {price_max:.0f}")

    if price_min is not None and listing.price is not None and listing.price < price_min:
        reasons.append(f"price {listing.price} below min {price_min:.0f}")

    if (
        search_cfg.min_rooms is not None
        and listing.rooms is not None
        and listing.rooms < search_cfg.min_rooms
    ):
        reasons.append(f"{listing.rooms} rooms, need at least {search_cfg.min_rooms}")

    if (
        search_cfg.min_available_rooms is not None
        and listing.available_rooms is not None
        and listing.available_rooms < search_cfg.min_available_rooms
    ):
        reasons.append(
            f"{listing.available_rooms} available rooms, need at least "
            f"{search_cfg.min_available_rooms}"
        )

    if (
        search_cfg.max_available_rooms is not None
        and listing.available_rooms is not None
        and listing.available_rooms > search_cfg.max_available_rooms
    ):
        reasons.append(
            f"{listing.available_rooms} available rooms, max is {search_cfg.max_available_rooms}"
        )

    if search_cfg.excluded_keywords:
        lowered = listing.raw_text.lower()
        hit = [k for k in search_cfg.excluded_keywords if k.lower() in lowered]
        if hit:
            reasons.append(f"contains excluded keyword: {', '.join(hit)}")

    if _mentions_broker(listing.raw_text):
        reasons.append("mentions a broker/agency")

    if _mentions_girls_only(listing.raw_text):
        reasons.append("restricted to women/girls only")

    if (
        search_cfg.max_roommates is not None
        and listing.roommates is not None
        and listing.roommates > search_cfg.max_roommates
    ):
        reasons.append(f"{listing.roommates} roommates, max is {search_cfg.max_roommates}")

    if search_cfg.neighborhoods and not location_ok(listing, search_cfg, zone_cfg):
        if zone_cfg and zone_cfg.active and listing.distance_m is None:
            # A zone IS configured, but this listing hasn't been geocoded
            # yet (explain_mismatch can run before cli.py's _geocode_listing
            # call, on a listing that already failed a cheaper check) — so
            # "outside the zone radius" would be misleading; nothing about
            # distance has actually been checked.
            reasons.append("neighborhood not in profile's list (location not yet checked)")
        else:
            reasons.append(
                "neighborhood not in profile's list and outside the zone radius"
                if zone_cfg and zone_cfg.active
                else "neighborhood not in profile's list (no zone configured as a fallback)"
            )

    return reasons


def location_ok(listing: Listing, search_cfg: SearchConfig, zone_cfg: ZoneConfig | None) -> bool:
    """The neighborhoods/zone-distance check, split out from
    matches_without_location so it can run AFTER geocoding (see
    matches())."""
    if not search_cfg.neighborhoods:
        return True
    # listing.neighborhoods_mentioned is extracted once per post against
    # the UNION of every configured profile's neighborhoods (see
    # Config.all_neighborhoods), so here we narrow it down to just this
    # profile's own list — required now that different profiles can
    # configure different neighborhoods.
    profile_hit = any(n in search_cfg.neighborhoods for n in listing.neighborhoods_mentioned)
    # A neighborhood-keyword miss is still a match if the listing geocoded
    # within the configured zone radius (see zones.py) — the two are OR'd
    # so a missing/failed geocode never regresses the existing
    # keyword-only behavior.
    return bool(profile_hit or (zone_cfg and within_zone(listing.distance_m, zone_cfg)))
