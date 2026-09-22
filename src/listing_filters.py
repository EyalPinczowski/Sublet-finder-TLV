from __future__ import annotations

from .config import SearchConfig, ZoneConfig
from .listing_models import Listing
from .zones import within_zone


def matches(listing: Listing, search_cfg: SearchConfig, zone_cfg: ZoneConfig | None = None) -> bool:
    if (
        search_cfg.price_max is not None
        and listing.price is not None
        and listing.price > search_cfg.price_max
    ):
        return False

    if (
        search_cfg.price_min is not None
        and listing.price is not None
        and listing.price < search_cfg.price_min
    ):
        return False

    if (
        search_cfg.min_rooms is not None
        and listing.rooms is not None
        and listing.rooms < search_cfg.min_rooms
    ):
        return False

    if search_cfg.neighborhoods and not listing.neighborhoods_mentioned:
        # A neighborhood-keyword miss is still a match if the listing
        # geocoded within the configured zone radius (see zones.py) — the
        # two are OR'd so a missing/failed geocode never regresses the
        # existing keyword-only behavior.
        if not (zone_cfg and within_zone(listing.distance_m, zone_cfg)):
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
