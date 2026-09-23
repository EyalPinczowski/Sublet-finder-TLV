from __future__ import annotations

from datetime import date, timedelta

from .config import SearchConfig, StayConfig, ZoneConfig
from .listing_models import Listing
from .zones import within_zone


def _resolve_dates(listing: Listing) -> tuple[date | None, int | None]:
    """(start_date, duration_days) reconciled from whatever combination of
    lease_start_date/lease_end_date/lease_duration_days was actually
    extracted (a date range, a start date + stated duration, or a bare
    duration) — the single place this logic lives, so the LLM and regex
    extraction paths and this filter never disagree on it."""
    start = listing.lease_start_date
    duration = listing.lease_duration_days
    if duration is None and start is not None and listing.lease_end_date is not None:
        duration = (listing.lease_end_date - start).days
    return start, duration


def matches(
    listing: Listing,
    search_cfg: SearchConfig,
    zone_cfg: ZoneConfig | None = None,
    stay_cfg: StayConfig | None = None,
    today: date | None = None,
) -> bool:
    price_min, price_max = search_cfg.price_min, search_cfg.price_max

    if stay_cfg is not None:
        start, duration = _resolve_dates(listing)
        # HARD gate — unlike every other field in this function, dates are
        # REQUIRED, not soft-optional: a listing with no date/duration info
        # at all is dropped rather than shown as a maybe. Deliberate
        # exception to this tool's usual "missing data passes" rule; see
        # README "Stay length and dates".
        if duration is None:
            return False
        if duration < stay_cfg.min_days:
            return False
        if start is not None:
            window_start = today or date.today()
            window_end = window_start + timedelta(days=stay_cfg.search_window_days)
            if not (window_start <= start <= window_end):
                return False
        # Prorate the monthly budget down for a stay under a month, since
        # listing.price for a short sublet is the TOTAL for its stated
        # period, not a monthly rate. Never prorate UP for a longer stay —
        # normal monthly-rate listings are unaffected.
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

    if search_cfg.neighborhoods:
        # listing.neighborhoods_mentioned is extracted once per post against
        # the UNION of every configured profile's neighborhoods (see
        # Config.all_neighborhoods), so here we narrow it down to just this
        # profile's own list — required now that different profiles can
        # configure different neighborhoods.
        profile_hit = any(n in search_cfg.neighborhoods for n in listing.neighborhoods_mentioned)
        # A neighborhood-keyword miss is still a match if the listing
        # geocoded within the configured zone radius (see zones.py) — the
        # two are OR'd so a missing/failed geocode never regresses the
        # existing keyword-only behavior.
        if not profile_hit and not (zone_cfg and within_zone(listing.distance_m, zone_cfg)):
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

    if (
        search_cfg.max_roommates is not None
        and listing.roommates is not None
        and listing.roommates > search_cfg.max_roommates
    ):
        return False

    if not _bathrooms_ok(listing, search_cfg):
        return False

    return True


def _bathrooms_ok(listing: Listing, search_cfg: SearchConfig) -> bool:
    """The bathroom rule is satisfied if ANY of: the apartment has at least
    min_bathrooms toilets, there's a toilet per roommate, or the toilet and
    shower are separate rooms and roommates <=
    separate_toilet_shower_max_roommates. Not enough info to judge -> pass
    through, same as the other soft filters above."""
    if not (search_cfg.min_bathrooms or search_cfg.separate_toilet_shower_max_roommates):
        return True

    if listing.toilets is None and not listing.separate_toilet_shower:
        return True

    if (
        search_cfg.min_bathrooms is not None
        and listing.toilets is not None
        and listing.toilets >= search_cfg.min_bathrooms
    ):
        return True

    if (
        listing.toilets is not None
        and listing.roommates is not None
        and listing.toilets >= listing.roommates
    ):
        return True

    if (
        listing.separate_toilet_shower
        and search_cfg.separate_toilet_shower_max_roommates is not None
        and (
            listing.roommates is None
            or listing.roommates <= search_cfg.separate_toilet_shower_max_roommates
        )
    ):
        return True

    return False
