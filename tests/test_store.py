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


def test_insert_and_find_by_content_hash(isolated_db):
    listing = make_listing()
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        found = store.find_by_content_hash(conn, store.content_hash_key(listing))
        assert found == listing.post_url


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


def test_effective_score_adds_save_bonus(isolated_db):
    listing = make_listing(score=50)
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        row = store.list_listings(conn, matched_only=True)[0]
        assert store.effective_score(conn, row) == 50
        store.add_mark(conn, listing.post_url, "user1", "save")
        assert store.effective_score(conn, row) == 50 + store.MARK_SCORE_DELTA


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
