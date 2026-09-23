from src.config import SearchConfig, ZoneConfig
from src.listing_models import Listing
from src.scoring import breakdown, score, stars, top_factors


def make_listing(**overrides) -> Listing:
    defaults = dict(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="Secret Tel Aviv",
        raw_text="sublet",
        price=3300,
        rooms=3.0,
        roommates=2,
        toilets=2,
    )
    defaults.update(overrides)
    return Listing(**defaults)


def factor(parts, label_prefix):
    for label, delta in parts:
        if label.startswith(label_prefix) or label == label_prefix:
            return delta
    raise AssertionError(f"no factor starting with {label_prefix!r} in {parts}")


def test_zone_points_close_beats_far():
    search = SearchConfig()
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    close = make_listing(distance_m=200)
    far = make_listing(distance_m=900)
    close_pts = factor(breakdown(close, search, zone), "200m")
    far_pts = factor(breakdown(far, search, zone), "900m")
    assert close_pts > far_pts


def test_zone_points_beyond_cutoff_is_zero():
    search = SearchConfig()
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    far = make_listing(distance_m=5000)
    assert factor(breakdown(far, search, zone), "5000m") == 0


def test_zone_unknown_beats_no_zone_config_neighborhood_fallback():
    # Neighborhood-only match scores lower than fully-unknown location — a
    # keyword hit with no coordinate is weaker evidence than "we simply
    # don't know", per the neutral-fill principle.
    search = SearchConfig()
    with_neighborhood = make_listing(distance_m=None, neighborhoods_mentioned=["florentin"])
    unknown = make_listing(distance_m=None, neighborhoods_mentioned=[])
    nbhd_pts = factor(breakdown(with_neighborhood, search, None), "neighborhood match")
    unknown_pts = factor(breakdown(unknown, search, None), "location unknown")
    assert unknown_pts > nbhd_pts


def test_price_at_minimum_scores_higher_than_at_maximum():
    search = SearchConfig(price_min=3000, price_max=3600)
    cheap = make_listing(price=3000)
    expensive = make_listing(price=3600)
    cheap_pts = factor(breakdown(cheap, search), "3000 ILS")
    expensive_pts = factor(breakdown(expensive, search), "3600 ILS")
    assert cheap_pts > expensive_pts


def test_price_missing_is_neutral_not_worst():
    search = SearchConfig(price_min=3000, price_max=3600)
    expensive = make_listing(price=3600)
    unknown = make_listing(price=None)
    expensive_pts = factor(breakdown(expensive, search), "3600 ILS")
    unknown_pts = factor(breakdown(unknown, search), "price not listed")
    assert unknown_pts >= expensive_pts


def test_rooms_meeting_minimum_scores_full():
    search = SearchConfig(min_rooms=2.0)
    listing = make_listing(rooms=3.0)
    assert factor(breakdown(listing, search), "3.0 rooms") == 15


def test_roommates_fewer_scores_higher():
    search = SearchConfig(max_roommates=3)
    two = make_listing(roommates=2)
    three = make_listing(roommates=3)
    two_pts = factor(breakdown(two, search), "2 roommates")
    three_pts = factor(breakdown(three, search), "3 roommates")
    assert two_pts > three_pts


def test_bathrooms_are_not_a_scoring_factor():
    """Bathroom count is a filter concern (listing_filters._bathrooms_ok),
    not a ranking one — two listings differing only in toilets should
    score identically, and no factor label should mention bathrooms."""
    search = SearchConfig(min_bathrooms=2)
    plenty = make_listing(toilets=3)
    few = make_listing(toilets=1, separate_toilet_shower=False)
    assert score(plenty, search) == score(few, search)
    assert not any("bathroom" in label for label, _ in breakdown(plenty, search))


def test_freshness_newer_scores_higher():
    search = SearchConfig()
    fresh = make_listing()
    stale = make_listing()
    fresh_parts = breakdown(fresh, search, age_hours=12)
    stale_parts = breakdown(stale, search, age_hours=24 * 10)
    assert factor(fresh_parts, "posted") > factor(stale_parts, "posted")


def test_photo_bonus_only_when_images_present():
    search = SearchConfig()
    with_photo = make_listing(images=["https://example.com/a.jpg"])
    without_photo = make_listing(images=[])
    assert any(label == "has photos" for label, _ in breakdown(with_photo, search))
    assert not any(label == "has photos" for label, _ in breakdown(without_photo, search))


def test_score_is_clamped_0_to_100():
    search = SearchConfig(price_min=3000, price_max=3600, min_rooms=2.0, max_roommates=3)
    zone = ZoneConfig(target_lat=32.0768, target_lon=34.7742, max_distance_meters=1000)
    great = make_listing(
        price=3000, rooms=4.0, roommates=1, toilets=3, distance_m=100,
        images=["https://example.com/a.jpg"],
    )
    s = score(great, search, zone, age_hours=1)
    assert 0 <= s <= 100


def test_stars_thresholds():
    assert stars(90) == "⭐" * 5
    assert stars(75) == "⭐" * 4
    assert stars(60) == "⭐" * 3
    assert stars(40) == "⭐" * 2
    assert stars(10) == "⭐" * 1


def test_top_factors_returns_highest_first():
    parts = [("a", 5), ("b", 25), ("c", 10)]
    assert top_factors(parts, n=2) == [("b", 25), ("c", 10)]


def test_price_scoring_is_prorated_consistently_with_the_filter():
    # A 15-day listing at 1800 ILS sits at the very TOP of the prorated
    # budget (2700-3600 prorated to 15/30 = 1350-1800) — matches.py accepts
    # it, but only just. Scoring must see the same prorated range, not the
    # raw monthly one, or a listing barely affordable for its actual
    # duration would score as if it were the cheapest option available.
    search = SearchConfig(price_min=2700, price_max=3600)
    listing = make_listing(price=1800, lease_duration_days=15)
    pts = factor(breakdown(listing, search), "1800 ILS")
    assert pts <= 10  # near the expensive end of the prorated range, not 25

    cheap = make_listing(price=1350, lease_duration_days=15)  # at prorated min
    cheap_pts = factor(breakdown(cheap, search), "1350 ILS")
    assert cheap_pts == 25


def test_price_scoring_is_not_prorated_for_a_month_long_stay():
    search = SearchConfig(price_min=2700, price_max=3600)
    listing = make_listing(price=2700, lease_duration_days=45)  # factor capped at 1.0
    pts = factor(breakdown(listing, search), "2700 ILS")
    assert pts == 25  # at the raw (unprorated) minimum, same as no duration at all
