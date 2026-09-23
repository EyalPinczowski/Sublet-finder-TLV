import publish

from src import store
from src.listing_models import Listing


def _seed(conn):
    listing = Listing(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="Secret Tel Aviv",
        raw_text="raw text",
        price=3300,
        rooms=3.0,
        address="דיזנגוף 120",
        phone="050-1234567",
        summary="Nice place",
        score=80,
    )
    store.insert_listing(conn, listing, matched_profiles=["default"])
    return listing


def test_render_snapshot_includes_listing_fields(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)
        snapshot = publish.render_snapshot(conn)
    assert "3300" in snapshot
    assert "דיזנגוף 120" in snapshot
    assert listing.post_url in snapshot


def test_render_snapshot_shows_lease_dates(isolated_db):
    from datetime import date

    listing = Listing(
        post_url="https://facebook.com/groups/1/posts/2",
        group_name="Secret Tel Aviv",
        raw_text="raw text",
        price=3300,
        lease_start_date=date(2026, 11, 1),
        lease_duration_days=14,
        score=80,
    )
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        snapshot = publish.render_snapshot(conn)
    assert "2026-11-01" in snapshot
    assert "14 days" in snapshot


def test_render_snapshot_is_noindex(isolated_db):
    with store.connect() as conn:
        snapshot = publish.render_snapshot(conn)
    assert 'name="robots" content="noindex"' in snapshot


def test_publish_skips_when_site_repo_url_unset(monkeypatch, capsys):
    monkeypatch.delenv("SITE_REPO_URL", raising=False)
    publish.publish()
    assert "skipping" in capsys.readouterr().out
