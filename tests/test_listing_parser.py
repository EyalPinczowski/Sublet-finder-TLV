from src.listing_parser import is_offer_listing, parse_listing


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


def test_parse_listing_detects_separate_toilet_shower():
    listing = parse_listing(
        "סאבלט עם שירותים נפרדים, 3000 שקל",
        post_url="https://facebook.com/groups/1/posts/5",
        group_name="Secret Tel Aviv",
        known_neighborhoods=[],
    )

    assert listing.separate_toilet_shower is True
