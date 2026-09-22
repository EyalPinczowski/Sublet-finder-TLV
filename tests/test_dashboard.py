import dashboard

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
        images=["https://example.com/a.jpg"],
    )
    store.insert_listing(conn, listing, matched=True)
    return listing


def test_render_page_includes_listing_fields(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)
        page = dashboard.render_page(conn, "tok")
    assert "3300" in page
    assert "דיזנגוף 120" in page
    assert "050-1234567" in page
    assert listing.post_url in page
    assert "tok" in page  # vote links carry the token


def test_render_page_excludes_dismissed_listings(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)
        store.add_mark(conn, listing.post_url, "dashboard", "dismiss")
        page = dashboard.render_page(conn, "tok")
    assert "No matches yet" in page


def test_get_token_uses_env_var(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "TOKEN_PATH", tmp_path / "dashboard_token.txt")
    monkeypatch.setenv("DASHBOARD_TOKEN", "explicit-token")
    assert dashboard._get_token() == "explicit-token"


def test_get_token_generates_and_persists_when_unset(monkeypatch, tmp_path):
    monkeypatch.setattr(dashboard, "TOKEN_PATH", tmp_path / "dashboard_token.txt")
    monkeypatch.delenv("DASHBOARD_TOKEN", raising=False)
    token = dashboard._get_token()
    assert token
    assert dashboard.TOKEN_PATH.read_text().strip() == token
    # A second call reuses the persisted token.
    assert dashboard._get_token() == token
