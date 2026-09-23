from src import store
from src.listing_models import Listing


def make_listing(**overrides) -> Listing:
    defaults = dict(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="Secret Tel Aviv",
        raw_text="sublet in florentin, 4500 nis",
        price=4500,
        rooms=2.0,
        address="דיזנגוף 120",
    )
    defaults.update(overrides)
    return Listing(**defaults)


def test_content_hash_key_none_without_address():
    assert store.content_hash_key(make_listing(address=None)) is None


def test_content_hash_key_stable_for_same_listing():
    a = store.content_hash_key(make_listing())
    b = store.content_hash_key(make_listing())
    assert a == b


def test_content_hash_key_differs_for_different_address():
    a = store.content_hash_key(make_listing(address="דיזנגוף 120"))
    b = store.content_hash_key(make_listing(address="רוטשילד 5"))
    assert a != b


def test_content_hash_key_ignores_street_prefix():
    """"רחוב דיזנגוף 120" and "דיזנגוף 120" must hash the same — this is
    exactly the kind of wording difference two independent posts of the
    SAME apartment (one per group) commonly have."""
    a = store.content_hash_key(make_listing(address="דיזנגוף 120"))
    b = store.content_hash_key(make_listing(address="רחוב דיזנגוף 120"))
    assert a == b


def test_content_hash_key_ignores_city_name_suffix():
    a = store.content_hash_key(make_listing(address="דיזנגוף 120"))
    b = store.content_hash_key(make_listing(address="דיזנגוף 120, תל אביב"))
    assert a == b


def test_content_hash_key_ignores_small_price_variance():
    """A repost's price sometimes extracts (or genuinely gets tweaked)
    slightly differently — small variance within the same rounding bucket
    must still hash the same."""
    a = store.content_hash_key(make_listing(price=4480))
    b = store.content_hash_key(make_listing(price=4520))
    assert a == b


def test_content_hash_key_still_differs_for_a_real_price_difference():
    a = store.content_hash_key(make_listing(price=3500))
    b = store.content_hash_key(make_listing(price=4500))
    assert a != b


def test_content_hash_key_still_differs_for_different_rooms():
    a = store.content_hash_key(make_listing(rooms=2.0))
    b = store.content_hash_key(make_listing(rooms=3.0))
    assert a != b


def test_content_hash_key_none_when_address_is_only_city_boilerplate():
    """An address that's just a bare city reference (e.g. the LLM
    extracted "תל אביב" with no street — an allowed, real case) must not
    hash at all: normalizing it strips everything, and hashing an empty
    string would collide every such listing together regardless of their
    actual (unknown) address."""
    assert store.content_hash_key(make_listing(address="תל אביב")) is None
    assert store.content_hash_key(make_listing(address="ת\"א")) is None
    assert store.content_hash_key(make_listing(address="רחוב תל אביב")) is None


def test_content_hash_key_price_rounding_is_symmetric_at_the_boundary():
    """Python's round() uses round-half-to-even, which would put 4450 and
    4460 — a plausible same-listing repost variance — in different
    100-ILS buckets; rounding must be symmetric instead."""
    a = store.content_hash_key(make_listing(price=4450))
    b = store.content_hash_key(make_listing(price=4460))
    assert a == b


def test_insert_and_find_by_content_hash(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        found = store.find_by_content_hash(conn, store.content_hash_key(listing))
        assert found == listing.post_url


def test_phone_hash_key_none_without_phone():
    assert store.phone_hash_key(make_listing(phone=None)) is None


def test_phone_hash_key_stable_for_same_listing():
    a = store.phone_hash_key(make_listing(phone="050-1234567"))
    b = store.phone_hash_key(make_listing(phone="050-1234567"))
    assert a == b


def test_phone_hash_key_ignores_formatting_differences():
    a = store.phone_hash_key(make_listing(phone="050-1234567"))
    b = store.phone_hash_key(make_listing(phone="0501234567"))
    assert a == b


def test_phone_hash_key_differs_for_different_phone():
    a = store.phone_hash_key(make_listing(phone="050-1234567"))
    b = store.phone_hash_key(make_listing(phone="052-7654321"))
    assert a != b


def test_phone_hash_key_ignores_small_price_variance():
    a = store.phone_hash_key(make_listing(phone="050-1234567", price=4480))
    b = store.phone_hash_key(make_listing(phone="050-1234567", price=4520))
    assert a == b


def test_insert_and_find_by_phone_hash(isolated_db):
    listing = make_listing(phone="050-1234567")
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        found = store.find_by_phone_hash(conn, store.phone_hash_key(listing))
        assert found == listing.post_url


def test_find_by_phone_hash_none_when_no_phone(isolated_db):
    with store.connect() as conn:
        assert store.find_by_phone_hash(conn, None) is None


def test_connect_migrates_a_pre_existing_db_missing_phone_hash(isolated_db):
    """A DB created before the phone_hash column existed must still work —
    connect() adds the column (and its index) on the fly rather than
    failing on the next insert."""
    import sqlite3

    conn = sqlite3.connect(store.DB_PATH)
    conn.executescript(
        """
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_url TEXT UNIQUE NOT NULL,
            group_name TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            price INTEGER, rooms REAL, neighborhoods TEXT, roommates INTEGER,
            toilets INTEGER, available_rooms INTEGER, lease_start_date TEXT,
            lease_end_date TEXT, lease_duration_days INTEGER, address TEXT,
            phone TEXT, images TEXT, summary TEXT, lat REAL, lon REAL,
            distance_m REAL, score INTEGER, content_hash TEXT,
            matched INTEGER NOT NULL DEFAULT 0, matched_profiles TEXT,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()

    listing = make_listing(phone="050-1111111")
    with store.connect() as conn:
        listing_id = store.insert_listing(conn, listing, matched_profiles=["default"])
        assert listing_id
        row = store.list_listings(conn, matched_only=True)[0]
        assert row.phone_hash == store.phone_hash_key(listing)
    with store.connect() as conn:  # a second connect() must stay a no-op/idempotent
        assert len(store.list_listings(conn, matched_only=True)) == 1


def test_connect_migrates_an_ancient_db_missing_many_columns(isolated_db):
    """Regression test: _ensure_schema_upgrades used to special-case only
    phone_hash (the most recent addition at the time), which meant a DB old
    enough to predate an EARLIER addition like available_rooms still broke
    insert_listing() with "no such column". A DB with only the very
    original core columns must now be migrated to the full current schema
    on connect(), not just have phone_hash bolted on."""
    import sqlite3

    conn = sqlite3.connect(store.DB_PATH)
    conn.executescript(
        """
        CREATE TABLE listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            post_url TEXT UNIQUE NOT NULL,
            group_name TEXT NOT NULL,
            raw_text TEXT NOT NULL,
            matched INTEGER NOT NULL DEFAULT 0,
            notified INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        """
    )
    conn.commit()
    conn.close()

    listing = make_listing(available_rooms=1, phone="050-2222222")
    with store.connect() as conn:
        listing_id = store.insert_listing(conn, listing, matched_profiles=["default"])
        assert listing_id
        row = store.list_listings(conn, matched_only=True)[0]
        assert row.available_rooms == 1
        assert row.phone_hash == store.phone_hash_key(listing)


def test_mark_listing_dead_hides_it_like_a_dismiss(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        assert len(store.list_listings(conn, matched_only=True)) == 1
        store.mark_listing_dead(conn, listing.post_url)
        assert store.list_listings(conn, matched_only=True) == []
        assert store.is_dismissed(conn, listing.post_url) is True


def test_insert_ignores_duplicate_post_url(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        first_id = store.insert_listing(conn, listing, matched_profiles=["default"])
        second_id = store.insert_listing(conn, listing, matched_profiles=["default"])
    assert first_id
    assert second_id is None  # INSERT OR IGNORE hit the UNIQUE constraint


def test_listing_seen(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        assert store.listing_seen(conn, listing.post_url) is False
        store.insert_listing(conn, listing, matched_profiles=["default"])
        assert store.listing_seen(conn, listing.post_url) is True


def test_dismiss_hides_listing_from_default_listing(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        assert len(store.list_listings(conn, matched_only=True)) == 1
        store.add_mark(conn, listing.post_url, "user1", "dismiss")
        assert store.list_listings(conn, matched_only=True) == []
        assert len(store.list_listings(conn, matched_only=True, include_dismissed=True)) == 1


def test_effective_scores_adds_save_bonus(isolated_db):
    listing = make_listing(score=50)
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        rows = store.list_listings(conn, matched_only=True)
        assert store.effective_scores(conn, rows)[listing.post_url] == 50
        store.add_mark(conn, listing.post_url, "user1", "save")
        assert (
            store.effective_scores(conn, rows)[listing.post_url]
            == 50 + store.MARK_SCORE_DELTA
        )


def test_effective_scores_batch_computes_each_row_independently(isolated_db):
    a = make_listing(post_url="https://facebook.com/groups/1/posts/a", score=50)
    b = make_listing(post_url="https://facebook.com/groups/1/posts/b", score=70)
    with store.connect() as conn:
        store.insert_listing(conn, a, matched_profiles=["default"])
        store.insert_listing(conn, b, matched_profiles=["default"])
        store.add_mark(conn, a.post_url, "user1", "save")
        rows = store.list_listings(conn, matched_only=True)
        batch = store.effective_scores(conn, rows)
        assert batch[a.post_url] == 50 + store.MARK_SCORE_DELTA
        assert batch[b.post_url] == 70


def test_effective_scores_empty_list(isolated_db):
    with store.connect() as conn:
        assert store.effective_scores(conn, []) == {}


def test_recent_matched_http_urls_orders_newest_first_and_respects_limit(isolated_db):
    with store.connect() as conn:
        for i in range(3):
            listing = make_listing(post_url=f"https://facebook.com/groups/1/posts/{i}")
            store.insert_listing(conn, listing, matched_profiles=["default"])
        urls = store.recent_matched_http_urls(conn, limit=2)
        assert len(urls) == 2
        assert urls[0] == "https://facebook.com/groups/1/posts/2"


def test_recent_matched_http_urls_excludes_dismissed(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        store.mark_listing_dead(conn, listing.post_url)
        assert store.recent_matched_http_urls(conn, limit=20) == []


def test_recent_matched_http_urls_excludes_synthetic_text_sig_urls(isolated_db):
    listing = make_listing(post_url="text:abc123")
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        assert store.recent_matched_http_urls(conn, limit=20) == []


def test_add_mark_upserts_on_conflict(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        store.add_mark(conn, listing.post_url, "user1", "save")
        store.add_mark(conn, listing.post_url, "user1", "dismiss")
        assert store.is_dismissed(conn, listing.post_url) is True
        assert store.save_count(conn, listing.post_url) == 0


def test_callback_token_round_trip(isolated_db):
    with store.connect() as conn:
        token = store.callback_token(conn, "https://facebook.com/groups/1/posts/1")
        assert store.post_url_for_token(conn, token) == "https://facebook.com/groups/1/posts/1"


def test_callback_token_is_stable_for_same_post_url(isolated_db):
    with store.connect() as conn:
        a = store.callback_token(conn, "https://facebook.com/x")
        b = store.callback_token(conn, "https://facebook.com/x")
        assert a == b


def test_post_url_for_unknown_token_is_none(isolated_db):
    with store.connect() as conn:
        assert store.post_url_for_token(conn, "does-not-exist") is None


def test_image_urls_round_trip_through_json(isolated_db):
    listing = make_listing(images=["https://example.com/a.jpg", "https://example.com/b.jpg"])
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        row = store.list_listings(conn, matched_only=True)[0]
        assert row.image_urls() == ["https://example.com/a.jpg", "https://example.com/b.jpg"]


def test_lease_dates_are_persisted(isolated_db):
    from datetime import date

    listing = make_listing(
        lease_start_date=date(2026, 11, 1),
        lease_end_date=date(2026, 11, 20),
        lease_duration_days=19,
    )
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        row = store.list_listings(conn, matched_only=True)[0]
    assert row.lease_start_date == "2026-11-01"
    assert row.lease_end_date == "2026-11-20"
    assert row.lease_duration_days == 19


def test_lease_dates_are_null_when_unknown(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        row = store.list_listings(conn, matched_only=True)[0]
    assert row.lease_start_date is None
    assert row.lease_end_date is None
    assert row.lease_duration_days is None
