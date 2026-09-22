from src.config import SearchConfig, ZoneConfig
from src.listing_filters import matches
from src.listing_models import Listing


def make_listing(**overrides) -> Listing:
    defaults = dict(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="Secret Tel Aviv",
        raw_text="sublet in florentin, 4500 nis",
        price=4500,
        rooms=2.0,
        neighborhoods_mentioned=["florentin"],
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_matches_within_price_range():
    listing = make_listing(price=4500)
    cfg = SearchConfig(price_max=5000, price_min=3000)
    assert matches(listing, cfg) is True


def test_rejects_over_price_max():
    listing = make_listing(price=6000)
    cfg = SearchConfig(price_max=5000)
    assert matches(listing, cfg) is False


def test_rejects_under_price_min():
    listing = make_listing(price=1000)
    cfg = SearchConfig(price_min=3000)
    assert matches(listing, cfg) is False


def test_missing_price_is_not_filtered_out():
    listing = make_listing(price=None)
    cfg = SearchConfig(price_max=5000)
    assert matches(listing, cfg) is True


def test_rejects_below_min_rooms():
    listing = make_listing(rooms=1.0)
    cfg = SearchConfig(min_rooms=2.0)
    assert matches(listing, cfg) is False


def test_neighborhood_filter_requires_a_match():
    listing = make_listing(neighborhoods_mentioned=[])
    cfg = SearchConfig(neighborhoods=["florentin", "rothschild"])
    assert matches(listing, cfg) is False


def test_neighborhood_filter_passes_with_match():
    listing = make_listing(neighborhoods_mentioned=["florentin"])
    cfg = SearchConfig(neighborhoods=["florentin", "rothschild"])
    assert matches(listing, cfg) is True


def test_excluded_keyword_filters_out_listing():
    listing = make_listing(raw_text="sublet in florentin, roommates wanted")
    cfg = SearchConfig(excluded_keywords=["roommates wanted"])
    assert matches(listing, cfg) is False


def test_rejects_over_max_roommates():
    listing = make_listing(roommates=4)
    cfg = SearchConfig(max_roommates=3)
    assert matches(listing, cfg) is False


def test_allows_at_max_roommates():
    listing = make_listing(roommates=3)
    cfg = SearchConfig(max_roommates=3)
    assert matches(listing, cfg) is True


def test_missing_roommates_is_not_filtered_out():
    listing = make_listing(roommates=None)
    cfg = SearchConfig(max_roommates=3)
    assert matches(listing, cfg) is True


def test_bathroom_rule_passes_with_enough_toilets():
    listing = make_listing(toilets=2, roommates=3)
    cfg = SearchConfig(min_bathrooms=2, separate_toilet_shower_max_roommates=3)
    assert matches(listing, cfg) is True


def test_bathroom_rule_passes_with_toilet_per_roommate():
    listing = make_listing(toilets=1, roommates=1)
    cfg = SearchConfig(min_bathrooms=2, separate_toilet_shower_max_roommates=3)
    assert matches(listing, cfg) is True


def test_bathroom_rule_fails_when_short_on_toilets():
    listing = make_listing(toilets=1, roommates=2, separate_toilet_shower=False)
    cfg = SearchConfig(min_bathrooms=2, separate_toilet_shower_max_roommates=3)
    assert matches(listing, cfg) is False


def test_bathroom_rule_passes_with_separate_toilet_shower_under_cap():
    listing = make_listing(toilets=1, roommates=3, separate_toilet_shower=True)
    cfg = SearchConfig(min_bathrooms=2, separate_toilet_shower_max_roommates=3)
    assert matches(listing, cfg) is True


def test_bathroom_rule_rejects_separate_toilet_shower_over_cap():
    listing = make_listing(toilets=1, roommates=4, separate_toilet_shower=True)
    cfg = SearchConfig(min_bathrooms=2, separate_toilet_shower_max_roommates=3)
    assert matches(listing, cfg) is False


def test_bathroom_rule_passes_through_with_no_info():
    listing = make_listing(toilets=None, roommates=None, separate_toilet_shower=False)
    cfg = SearchConfig(min_bathrooms=2, separate_toilet_shower_max_roommates=3)
    assert matches(listing, cfg) is True


def test_zone_match_rescues_a_neighborhood_keyword_miss():
    # No neighborhood keyword hit, but the listing geocoded within the
    # configured zone radius — the OR path from geocode.py/zones.py.
    listing = make_listing(neighborhoods_mentioned=[], distance_m=400)
    cfg = SearchConfig(neighborhoods=["florentin", "rothschild"])
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    assert matches(listing, cfg, zone) is True


def test_zone_match_does_not_rescue_when_too_far():
    listing = make_listing(neighborhoods_mentioned=[], distance_m=5000)
    cfg = SearchConfig(neighborhoods=["florentin", "rothschild"])
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    assert matches(listing, cfg, zone) is False


def test_missing_zone_config_never_regresses_keyword_only_behavior():
    listing = make_listing(neighborhoods_mentioned=[], distance_m=100)
    cfg = SearchConfig(neighborhoods=["florentin", "rothschild"])
    assert matches(listing, cfg, zone_cfg=None) is False
