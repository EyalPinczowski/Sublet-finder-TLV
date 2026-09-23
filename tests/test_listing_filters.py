from datetime import date, timedelta

from src.config import SearchConfig, StayConfig, ZoneConfig
from src.listing_filters import _resolve_dates, location_ok, matches, matches_without_location
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


def test_matches_without_location_ignores_neighborhoods():
    """The whole point of the split: a listing that fails every
    neighborhood/zone check still passes the location-free phase, so
    cli.py can decide whether it's worth geocoding at all."""
    listing = make_listing(neighborhoods_mentioned=[])
    cfg = SearchConfig(neighborhoods=["florentin", "rothschild"])
    assert matches_without_location(listing, cfg) is True
    assert matches(listing, cfg) is False  # the full check still rejects it


def test_location_ok_no_neighborhoods_configured_passes():
    listing = make_listing(neighborhoods_mentioned=[])
    assert location_ok(listing, SearchConfig(), zone_cfg=None) is True


def test_location_ok_requires_a_match_or_zone_hit():
    listing = make_listing(neighborhoods_mentioned=[])
    cfg = SearchConfig(neighborhoods=["florentin"])
    assert location_ok(listing, cfg, zone_cfg=None) is False


def test_location_ok_passes_with_neighborhood_match():
    listing = make_listing(neighborhoods_mentioned=["florentin"])
    cfg = SearchConfig(neighborhoods=["florentin"])
    assert location_ok(listing, cfg, zone_cfg=None) is True


def test_matches_composes_both_phases():
    """Regression net for the matches()/matches_without_location()/
    location_ok() split: matches() must still equal the AND of both."""
    listing = make_listing(price=4500, neighborhoods_mentioned=["florentin"])
    cfg = SearchConfig(price_max=5000, neighborhoods=["florentin"])
    assert matches(listing, cfg) == (
        matches_without_location(listing, cfg) and location_ok(listing, cfg, None)
    )
    listing2 = make_listing(price=9000, neighborhoods_mentioned=["florentin"])
    assert matches(listing2, cfg) == (
        matches_without_location(listing2, cfg) and location_ok(listing2, cfg, None)
    )


def test_excluded_keyword_filters_out_listing():
    listing = make_listing(raw_text="sublet in florentin, roommates wanted")
    cfg = SearchConfig(excluded_keywords=["roommates wanted"])
    assert matches(listing, cfg) is False


def test_broker_mention_filters_out_listing():
    listing = make_listing(raw_text="דירה להשכרה בפלורנטין, לפרטים נא לפנות למתווך")
    assert matches(listing, SearchConfig()) is False


def test_broker_mention_variant_metavech_filters_out_listing():
    listing = make_listing(raw_text="הדירה מתווכת, נא לפנות")
    assert matches(listing, SearchConfig()) is False


def test_no_broker_fee_is_not_filtered_out():
    listing = make_listing(raw_text="דירה להשכרה בפלורנטין ללא תיווך")
    assert matches(listing, SearchConfig()) is True


def test_no_broker_fee_variant_bli_is_not_filtered_out():
    listing = make_listing(raw_text="דירה להשכרה בפלורנטין בלי תיווך")
    assert matches(listing, SearchConfig()) is True


def test_no_broker_fee_variant_ein_is_not_filtered_out():
    listing = make_listing(raw_text="דירה להשכרה בפלורנטין אין תיווך")
    assert matches(listing, SearchConfig()) is True


def test_negated_and_real_broker_mention_still_filters_out():
    listing = make_listing(raw_text="ללא תיווך לדירה זו, אך תיווך בלעדי לדירה הבאה")
    assert matches(listing, SearchConfig()) is False


def test_no_broker_terms_at_all_is_unaffected():
    listing = make_listing(raw_text="sublet in florentin, 4500 nis")
    assert matches(listing, SearchConfig()) is True


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


def test_neighborhoods_mentioned_is_narrowed_to_this_profiles_own_list():
    # neighborhoods_mentioned is extracted once against the UNION of every
    # configured profile's neighborhoods (Config.all_neighborhoods) — a
    # profile must only match on keywords that are actually in ITS OWN
    # list, not any profile's.
    listing = make_listing(neighborhoods_mentioned=["rothschild"])  # from another profile
    cfg = SearchConfig(neighborhoods=["florentin"])
    assert matches(listing, cfg) is False


def test_available_rooms_rejects_below_minimum():
    listing = make_listing(available_rooms=1)
    cfg = SearchConfig(min_available_rooms=2)
    assert matches(listing, cfg) is False


def test_available_rooms_allows_at_minimum():
    listing = make_listing(available_rooms=2)
    cfg = SearchConfig(min_available_rooms=2)
    assert matches(listing, cfg) is True


def test_available_rooms_rejects_above_maximum():
    listing = make_listing(available_rooms=3)
    cfg = SearchConfig(min_available_rooms=1, max_available_rooms=1)
    assert matches(listing, cfg) is False


def test_available_rooms_missing_is_not_filtered_out():
    listing = make_listing(available_rooms=None)
    cfg = SearchConfig(min_available_rooms=2)
    assert matches(listing, cfg) is True


def test_single_vs_two_room_profiles_distinguish_a_listing():
    single = SearchConfig(name="single room", min_available_rooms=1, max_available_rooms=1)
    pair = SearchConfig(name="two rooms", min_available_rooms=2)

    one_room_listing = make_listing(available_rooms=1)
    assert matches(one_room_listing, single) is True
    assert matches(one_room_listing, pair) is False

    two_room_listing = make_listing(available_rooms=2)
    assert matches(two_room_listing, single) is False
    assert matches(two_room_listing, pair) is True


TODAY = date(2026, 10, 1)


def test_resolve_dates_from_start_and_end():
    listing = make_listing(
        lease_start_date=date(2026, 11, 1), lease_end_date=date(2026, 11, 15)
    )
    start, duration = _resolve_dates(listing)
    assert start == date(2026, 11, 1)
    assert duration == 14


def test_resolve_dates_from_start_and_explicit_duration():
    listing = make_listing(lease_start_date=date(2026, 11, 1), lease_duration_days=14)
    start, duration = _resolve_dates(listing)
    assert start == date(2026, 11, 1)
    assert duration == 14


def test_resolve_dates_from_duration_only():
    listing = make_listing(lease_duration_days=14)
    start, duration = _resolve_dates(listing)
    assert start is None
    assert duration == 14


def test_resolve_dates_none_without_any_date_info():
    listing = make_listing()
    assert _resolve_dates(listing) == (None, None)


def test_resolve_dates_from_end_date_only_assumes_starting_today():
    # A post that only says when the lease ends most naturally reads as
    # "available now, until <end>" — it should not be treated as having no
    # date info at all (that would drop it under the hard gate even though
    # it did state something).
    listing = make_listing(lease_end_date=TODAY + timedelta(days=14))
    start, duration = _resolve_dates(listing, today=TODAY)
    assert start == TODAY
    assert duration == 14


def test_resolve_dates_end_date_already_past_is_unusable():
    listing = make_listing(lease_end_date=TODAY - timedelta(days=1))
    start, duration = _resolve_dates(listing, today=TODAY)
    assert duration is None


def test_stay_gate_matches_an_end_date_only_listing_within_the_minimum():
    listing = make_listing(lease_end_date=TODAY + timedelta(days=14))
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, SearchConfig(), stay_cfg=stay, today=TODAY) is True


def test_stay_gate_is_skipped_when_no_stay_config_given():
    # Existing behavior (no stay_cfg) must be completely unaffected — a
    # listing with no date info at all still matches, as it always has.
    listing = make_listing()
    cfg = SearchConfig()
    assert matches(listing, cfg) is True


def test_stay_gate_drops_a_listing_with_no_date_info():
    listing = make_listing()
    cfg = SearchConfig()
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, cfg, stay_cfg=stay, today=TODAY) is False


def test_stay_gate_drops_a_stay_shorter_than_minimum():
    listing = make_listing(lease_duration_days=10)
    cfg = SearchConfig()
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, cfg, stay_cfg=stay, today=TODAY) is False


def test_stay_gate_allows_a_stay_at_exactly_the_minimum():
    listing = make_listing(lease_duration_days=14)
    cfg = SearchConfig()
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, cfg, stay_cfg=stay, today=TODAY) is True


def test_search_window_allows_a_start_date_inside_the_window():
    listing = make_listing(lease_start_date=TODAY + timedelta(days=10), lease_duration_days=14)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, SearchConfig(), stay_cfg=stay, today=TODAY) is True


def test_search_window_drops_a_start_date_beyond_the_window():
    listing = make_listing(lease_start_date=TODAY + timedelta(days=30), lease_duration_days=14)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, SearchConfig(), stay_cfg=stay, today=TODAY) is False


def test_search_window_drops_a_start_date_in_the_past():
    listing = make_listing(lease_start_date=TODAY - timedelta(days=1), lease_duration_days=14)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, SearchConfig(), stay_cfg=stay, today=TODAY) is False


def test_search_window_is_skipped_for_a_duration_only_listing():
    # No resolvable start date, but it already satisfied the hard
    # dates-required gate via an explicit duration — the window check
    # only applies when a start date is actually known.
    listing = make_listing(lease_duration_days=14)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, SearchConfig(), stay_cfg=stay, today=TODAY) is True


def test_price_is_prorated_down_for_a_short_stay():
    # 15 days = half a month: budget 2700-3600 prorates to 1350-1800.
    listing = make_listing(price=1600, lease_duration_days=15)
    cfg = SearchConfig(price_min=2700, price_max=3600)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, cfg, stay_cfg=stay, today=TODAY) is True
    # The same listing against the RAW (unprorated) range would be
    # wrongly rejected — proving proration is actually doing something.
    assert matches(listing, cfg) is False


def test_price_proration_still_rejects_outside_the_prorated_range():
    listing = make_listing(price=1000, lease_duration_days=15)  # below prorated 1350
    cfg = SearchConfig(price_min=2700, price_max=3600)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, cfg, stay_cfg=stay, today=TODAY) is False


def test_price_is_not_prorated_for_a_month_long_stay():
    listing = make_listing(price=3600, lease_duration_days=45)  # factor capped at 1.0
    cfg = SearchConfig(price_min=2700, price_max=3600)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, cfg, stay_cfg=stay, today=TODAY) is True

    over_budget = make_listing(price=3700, lease_duration_days=45)
    assert matches(over_budget, cfg, stay_cfg=stay, today=TODAY) is False


def test_missing_price_still_passes_with_stay_config_given():
    # Missing price stays soft-optional even with the stay gate active —
    # only the date/duration requirement is hard.
    listing = make_listing(price=None, lease_duration_days=14)
    cfg = SearchConfig(price_min=2700, price_max=3600)
    stay = StayConfig(min_days=14, search_window_days=21)
    assert matches(listing, cfg, stay_cfg=stay, today=TODAY) is True
