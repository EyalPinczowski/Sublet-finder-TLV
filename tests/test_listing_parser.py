from datetime import date

from src.listing_parser import (
    _extract_address,
    _extract_available_rooms,
    _extract_duration_days,
    _extract_lease_dates,
    _extract_phone,
    _extract_price,
    _parse_date_token,
    is_offer_listing,
    looks_like_explicit_apartment_seeker,
    mentions_housing,
    parse_listing,
)


def test_is_offer_listing_detects_hebrew_offer():
    text = "סאבלט בפלורנטין, 2 חדרים, 4500 ₪ לחודש, פנוי מאוקטובר"
    assert is_offer_listing(text) is True


def test_is_offer_listing_detects_english_offer():
    text = "Sublet available in Florentin, 2 rooms, 4500 NIS/month"
    assert is_offer_listing(text) is True


def test_is_offer_listing_rejects_seeker_post():
    text = "מחפש/ת סאבלט באזור רוטשילד לחודש הבא"
    assert is_offer_listing(text) is False


def test_is_offer_listing_rejects_unrelated_post():
    text = "מי מכיר מסעדה טובה בפלורנטין?"
    assert is_offer_listing(text) is False


def test_looks_like_explicit_apartment_seeker_detects_hebrew():
    assert looks_like_explicit_apartment_seeker("מחפשת דירה בפלורנטין לחודש הבא") is True


def test_looks_like_explicit_apartment_seeker_detects_english():
    assert looks_like_explicit_apartment_seeker("Looking for an apartment in Florentin") is True


def test_looks_like_explicit_apartment_seeker_ignores_roommate_wanted_posts():
    """"מחפש שותף" ("looking for a roommate") is usually someone OFFERING a
    room in their own apartment, not seeking one — must not be caught by
    this narrower, high-precision check (unlike the broader
    is_offer_listing(), which would wrongly reject it)."""
    text = "מחפש שותף/ה לדירה שלי בפלורנטין, חדר פנוי מיידי"
    assert looks_like_explicit_apartment_seeker(text) is False


def test_looks_like_explicit_apartment_seeker_false_for_offer_post():
    text = "סאבלט בפלורנטין, 2 חדרים, 4500 ₪ לחודש"
    assert looks_like_explicit_apartment_seeker(text) is False


def test_mentions_housing_detects_sublet_keyword():
    assert mentions_housing("סאבלט בפלורנטין, 4500 ₪") is True
    assert mentions_housing("subletting my room downtown") is True


def test_mentions_housing_detects_apartment_room_and_roommate_words():
    assert mentions_housing("דירה יפה באזור המרכז") is True
    assert mentions_housing("חדר פנוי בדירת שותפים") is True
    assert mentions_housing("looking for a roommate for my apartment") is True
    assert mentions_housing("מחפש שותף לדירה שלי בפלורנטין") is True


def test_mentions_housing_false_for_unrelated_post():
    assert mentions_housing("מי ראה את המשחק אתמול? מטורף!") is False
    assert mentions_housing("selling a couch, barely used") is False


def test_parse_listing_extracts_price_rooms_and_neighborhood():
    listing = parse_listing(
        'סאבלט בפלורנטין, 2 חדרים, 4,500 ש"ח לחודש',
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="Secret Tel Aviv",
        known_neighborhoods=["פלורנטין", "florentin"],
    )

    assert listing.price == 4500
    assert listing.rooms == 2.0
    assert listing.neighborhoods_mentioned == ["פלורנטין"]


def test_parse_listing_handles_missing_fields():
    listing = parse_listing(
        "sublet available soon, message me for details",
        post_url="https://facebook.com/groups/1/posts/2",
        group_name="Secret Tel Aviv",
        known_neighborhoods=["florentin"],
    )

    assert listing.price is None
    assert listing.rooms is None
    assert listing.neighborhoods_mentioned == []
    assert listing.roommates is None
    assert listing.toilets is None
    assert listing.separate_toilet_shower is False


def test_parse_listing_extracts_roommates_and_toilets():
    listing = parse_listing(
        "סאבלט בכיכר דיזנגוף, 3 שותפים בדירה, 2 שירותים, 3000 שקל",
        post_url="https://facebook.com/groups/1/posts/3",
        group_name="Secret Tel Aviv",
        known_neighborhoods=["כיכר דיזנגוף"],
    )

    assert listing.roommates == 3
    assert listing.toilets == 2
    assert listing.price == 3000


def test_extract_rooms_ignores_construct_state_bathroom_phrase():
    listing = parse_listing(
        "סאבלט, 2 חדרי רחצה בדירה, 3000 שקל",
        post_url="https://facebook.com/groups/1/posts/4",
        group_name="Secret Tel Aviv",
        known_neighborhoods=[],
    )

    assert listing.rooms is None
    assert listing.toilets == 2


def test_extract_price_handles_plain_digits_without_thousands_separator():
    listing = parse_listing(
        "סאבלט בכרם התימנים, 3000 שקל לחודש",
        post_url="https://facebook.com/groups/1/posts/6",
        group_name="Secret Tel Aviv",
        known_neighborhoods=[],
    )

    assert listing.price == 3000


def test_extract_price_matches_per_month_phrasing_without_a_currency_word():
    assert _extract_price("סאבלט בפלורנטין, 4000 לחודש") == 4000


def test_extract_price_matches_bechodesh_phrasing():
    assert _extract_price("סאבלט, 3500 בחודש") == 3500


def test_extract_price_matches_a_price_label_prefix():
    assert _extract_price("סאבלט בפלורנטין. מחיר: 4500") == 4500


def test_extract_price_matches_total_for_period_phrasing():
    # "2,500 לכל התקופה" has no currency marker, no "per month" phrase,
    # and no "price:" label — a real gap a user hit on a short-term post.
    assert _extract_price("2,500 לכל התקופה (גמישה)") == 2500


def test_extract_price_matches_letkufa_variant():
    assert _extract_price("2500 לתקופה") == 2500


def test_extract_price_matches_sach_hakol_variant():
    assert _extract_price('2500 סה"כ') == 2500


def test_extract_price_matches_price_label_with_dash():
    assert _extract_price("Sublet in Florentin. Price - 4200") == 4200


def test_extract_price_matches_english_per_month_phrasing():
    assert _extract_price("Sublet in Florentin, 3800 a month") == 3800


def test_extract_price_still_none_for_a_bare_unqualified_number():
    """A number with no currency word, no "per month" phrase, and no
    "price:" label must not be guessed as a price — e.g. a room count or
    an address number sitting elsewhere in the text."""
    assert _extract_price("סאבלט, 3 חדרים ברחוב הרצל 44") is None


def test_extract_price_converts_a_weekly_rate_to_the_stay_total():
    # This project's price convention (see listing_filters.
    # matches_without_location's proration comment) treats a short-stay
    # listing's price as the TOTAL for its whole period, not a per-unit
    # rate — "1000 ש"ח לשבוע" for a 14-day stay is really 2000 total.
    assert _extract_price("1000 ש\"ח לשבוע", duration_days=14) == 2000


def test_extract_price_converts_a_daily_rate_to_the_stay_total():
    assert _extract_price("150 ליום", duration_days=10) == 1500


def test_extract_price_keeps_bare_rate_when_duration_unknown():
    # Can't compute a total without knowing the period — best-effort
    # fallback, same as the rest of this regex parser.
    assert _extract_price("1000 ש\"ח לשבוע") == 1000


def test_extract_price_per_month_phrasing_unaffected_by_rate_handling():
    assert _extract_price("2500 לחודש", duration_days=None) == 2500


def test_parse_listing_detects_separate_toilet_shower():
    listing = parse_listing(
        "סאבלט עם שירותים נפרדים, 3000 שקל",
        post_url="https://facebook.com/groups/1/posts/5",
        group_name="Secret Tel Aviv",
        known_neighborhoods=[],
    )

    assert listing.separate_toilet_shower is True


def test_extract_phone_normalizes_local_format():
    assert _extract_phone("סאבלט בפלורנטין, 050-1234567") == "050-1234567"


def test_extract_phone_normalizes_international_format():
    assert _extract_phone("call me at +972-50-1234567") == "050-1234567"


def test_extract_phone_returns_none_without_a_number():
    assert _extract_phone("סאבלט בפלורנטין, פנו בפרטי") is None


def test_extract_phone_keeps_a_non_israeli_international_number():
    # Some posts give a non-Israeli WhatsApp contact — the "+" marks it
    # as already carrying its own country code, so it's kept as-is
    # rather than forced into the Israeli 05X-XXXXXXX shape.
    text = "Subletting my room. WhatsApp +1 619 375 2500"
    assert _extract_phone(text) == "+1 619 375 2500"


def test_extract_address_finds_street_and_number():
    assert _extract_address("דיזנגוף 120, 3000 שקל") == "דיזנגוף 120"


def test_extract_address_skips_stopword_phrases():
    assert _extract_address("קומה 3, 3000 שקל") is None


def test_extract_address_skips_facebook_follow_timestamp_boilerplate():
    # Facebook's own post-header UI text ("Follow · 2 hours ago"), which
    # can end up inside raw_text — shaped exactly like a real address
    # (Hebrew word(s) + a number) but isn't one, and the "N hours ago"
    # part changes on every later scan, which would otherwise poison
    # content_hash_key's repost-matching into never matching itself.
    assert _extract_address("Nirit Natanel · מעקב לפני 2 שעות · סאבלט") is None


def test_parse_listing_populates_phone_address_summary_and_images():
    listing = parse_listing(
        "דיזנגוף 120, 050-1234567, 3000 שקל",
        post_url="https://facebook.com/groups/1/posts/7",
        group_name="Secret Tel Aviv",
        known_neighborhoods=[],
        images=["https://example.com/a.jpg"],
    )

    assert listing.phone == "050-1234567"
    assert listing.address == "דיזנגוף 120"
    assert listing.images == ["https://example.com/a.jpg"]
    assert listing.summary is not None


def test_extract_available_rooms_reads_a_number():
    assert _extract_available_rooms("2 חדרים פנויים בדירה משותפת") == 2
    assert _extract_available_rooms("2 חדרים מתפנים בקרוב") == 2


def test_extract_available_rooms_bare_singular_is_one():
    assert _extract_available_rooms("חדר פנוי בדירת שותפים") == 1
    assert _extract_available_rooms("מתפנה חדר בדירת 3 חדרים") == 1


def test_extract_available_rooms_none_without_a_phrase():
    assert _extract_available_rooms("סאבלט בפלורנטין, 4500 שקל") is None


def test_extract_available_rooms_distinct_from_total_rooms():
    # "מתפנה חדר בדירת 3 חדרים" -> 1 room available, 3 rooms total.
    text = "מתפנה חדר בדירת 3 חדרים"
    assert _extract_available_rooms(text) == 1


def test_extract_available_rooms_falls_back_to_bedroom_count():
    # A whole-apartment sublet with no explicit "X available" phrasing —
    # infer from how many bedrooms are mentioned instead.
    assert _extract_available_rooms("חדר שינה, סלון, חלל עבודה") == 1
    assert _extract_available_rooms("שני חדרי שינה, סלון גדול") == 2


def test_extract_available_rooms_living_room_alone_is_not_a_bedroom():
    assert _extract_available_rooms("סלון גדול, חלל עבודה, מרפסת") is None


def test_extract_available_rooms_prefers_explicit_availability_over_bedroom_count():
    # "חדר פנוי" already answers "how many are available" — the total
    # bedroom count of the apartment shouldn't override that.
    assert _extract_available_rooms("חדר פנוי בדירת 3 חדרי שינה") == 1


def test_extract_available_rooms_my_room_is_one_regardless_of_apartment_size():
    # "Subletting my room" in a 3-room apartment with another roommate
    # already living there — only the poster's own room is available,
    # not the apartment's total size or the existing roommate's room.
    text = (
        "Subletting my room 2 min from Dizengoff Square. Beautiful, clean "
        "3 room apartment. There is one other super nice, clean female "
        "roommate in the apartment."
    )
    assert _extract_available_rooms(text) == 1
    assert _extract_available_rooms("מסבלטת את החדר שלי בבר גיורא") == 1


def test_extract_available_rooms_my_room_does_not_match_my_rooms():
    assert _extract_available_rooms("Subletting my rooms in the apartment") is None


def test_parse_listing_populates_available_rooms():
    listing = parse_listing(
        "שני חדרים פנויים בדירה משותפת, 5000 שקל",
        post_url="https://facebook.com/groups/1/posts/8",
        group_name="Secret Tel Aviv",
        known_neighborhoods=[],
    )
    assert listing.available_rooms == 2


def test_extract_duration_days_from_word_phrase():
    assert _extract_duration_days("סאבלט לתקופה של שבועיים") == 14
    assert _extract_duration_days("סאבלט לתקופה של שבוע") == 7
    assert _extract_duration_days("סאבלט לחודש") == 30


def test_extract_duration_days_from_explicit_number():
    assert _extract_duration_days("סאבלט ל-10 ימים") == 10
    assert _extract_duration_days("סאבלט ל-3 שבועות") == 21
    assert _extract_duration_days("סאבלט ל-2 חודשים") == 60


def test_extract_duration_days_none_without_a_phrase():
    assert _extract_duration_days("סאבלט בפלורנטין, 4500 שקל") is None


def test_parse_date_token_infers_next_year_when_date_has_passed():
    today = date(2026, 10, 1)
    # Jan 1 has already passed relative to Oct 1 -> next year.
    assert _parse_date_token("1.1", today) == date(2027, 1, 1)


def test_parse_date_token_uses_this_year_when_date_is_ahead():
    today = date(2026, 10, 1)
    assert _parse_date_token("15.11", today) == date(2026, 11, 15)


def test_parse_date_token_respects_explicit_year():
    assert _parse_date_token("15.11.2027", date(2026, 10, 1)) == date(2027, 11, 15)


def test_parse_date_token_rejects_invalid_dates():
    assert _parse_date_token("40.13", date(2026, 10, 1)) is None
    assert _parse_date_token("not-a-date", date(2026, 10, 1)) is None


def test_extract_lease_dates_reads_a_date_range():
    today = date(2026, 10, 1)
    start, end, duration = _extract_lease_dates("הדירה פנויה מ-1.11 עד 20.11", today)
    assert start == date(2026, 11, 1)
    assert end == date(2026, 11, 20)
    assert duration is None


def test_extract_lease_dates_reads_a_bare_start_date():
    today = date(2026, 10, 1)
    start, end, duration = _extract_lease_dates("הדירה פנויה מ-15.11 לתקופה של שבועיים", today)
    assert start == date(2026, 11, 15)
    assert end is None
    assert duration == 14


def test_extract_lease_dates_returns_all_none_without_any_date_info():
    start, end, duration = _extract_lease_dates("סאבלט בפלורנטין, 4500 שקל")
    assert (start, end, duration) == (None, None, None)


def test_extract_lease_dates_skips_over_a_weekday_name_before_the_date():
    # "החל מיום שישי 25.9" — "starting from [the day] Friday, 25.9" —
    # a common phrasing that would otherwise stop the date from being
    # recognized at all, since it doesn't come immediately after "מ-".
    today = date(2026, 9, 23)
    start, end, duration = _extract_lease_dates(
        "פנוי לסאבלט לתקופה של שבועיים החל מיום שישי 25.9", today
    )
    assert start == date(2026, 9, 25)
    assert duration == 14


def test_parse_date_token_reads_a_spelled_out_hebrew_month():
    today = date(2026, 9, 1)
    assert _parse_date_token("27 בספטמבר", today) == date(2026, 9, 27)


def test_extract_lease_dates_reads_a_named_month_range():
    today = date(2026, 9, 1)
    start, end, duration = _extract_lease_dates(
        "כניסה מ-27 בספטמבר עד 30 באוקטובר", today
    )
    assert start == date(2026, 9, 27)
    assert end == date(2026, 10, 30)


def test_extract_lease_dates_named_month_day_range_takes_the_earlier_day():
    # "27-30 באוקטובר" — a day RANGE before the month name, describing a
    # flexible end window — the earlier day is the conservative estimate.
    today = date(2026, 9, 1)
    start, end, duration = _extract_lease_dates(
        "כניסה מ-1 באוקטובר עד 27-30 באוקטובר", today
    )
    assert end == date(2026, 10, 27)


def test_parse_listing_populates_lease_dates():
    listing = parse_listing(
        "הדירה פנויה מ-1.11 עד 20.11, 4500 שקל",
        post_url="https://facebook.com/groups/1/posts/9",
        group_name="Secret Tel Aviv",
        known_neighborhoods=[],
    )
    assert listing.lease_start_date is not None
    assert listing.lease_end_date is not None
