import threading
import urllib.error
import urllib.request
from contextlib import contextmanager
from http.server import HTTPServer

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
    store.insert_listing(conn, listing, matched_profiles=["default"])
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


def test_render_page_shows_lease_dates(isolated_db):
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
        page = dashboard.render_page(conn, "tok")
    assert "2026-11-01" in page
    assert "14 days" in page


def test_render_page_excludes_dismissed_listings(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)
        store.add_mark(conn, listing.post_url, "dashboard", "dismiss")
        page = dashboard.render_page(conn, "tok")
    assert "No matches yet" in page


def test_render_page_shows_map_marker_for_geocoded_listing(isolated_db):
    with store.connect() as conn:
        listing = Listing(
            post_url="https://facebook.com/groups/1/posts/3",
            group_name="Secret Tel Aviv",
            raw_text="raw text",
            price=3300,
            address="דיזנגוף 120",
            lat=32.0768,
            lon=34.7742,
            score=80,
        )
        store.insert_listing(conn, listing, matched_profiles=["default"])
        page = dashboard.render_page(conn, "tok")
    assert 'id="map"' in page
    assert "leaflet" in page.lower()
    assert "32.0768" in page
    assert "34.7742" in page


def test_render_page_omits_map_when_no_listing_has_coordinates(isolated_db):
    with store.connect() as conn:
        _seed(conn)  # no lat/lon
        page = dashboard.render_page(conn, "tok")
    assert 'id="map"' not in page


def test_render_page_marks_one_or_two_person_listings_small(isolated_db):
    with store.connect() as conn:
        small = Listing(
            post_url="https://facebook.com/groups/1/posts/4",
            group_name="Secret Tel Aviv",
            raw_text="raw text",
            price=3300,
            lat=32.0768,
            lon=34.7742,
            available_rooms=1,
            score=80,
        )
        other = Listing(
            post_url="https://facebook.com/groups/1/posts/5",
            group_name="Secret Tel Aviv",
            raw_text="raw text",
            price=3300,
            lat=32.08,
            lon=34.78,
            available_rooms=3,
            score=70,
        )
        store.insert_listing(conn, small, matched_profiles=["default"])
        store.insert_listing(conn, other, matched_profiles=["default"])
        page = dashboard.render_page(conn, "tok")
    assert '"category": "small"' in page
    assert '"category": "other"' in page
    assert '<span class="suitable-small">' in page
    assert '<span class="suitable-other">' in page


def test_render_page_omits_suitable_badge_when_available_rooms_unknown(isolated_db):
    with store.connect() as conn:
        _seed(conn)  # no available_rooms
        page = dashboard.render_page(conn, "tok")
    # The stylesheet always defines these classes; what must be absent is
    # an actual badge span using them.
    assert '<span class="suitable-small">' not in page
    assert '<span class="suitable-other">' not in page


def test_render_page_marks_missing_price_as_potential(isolated_db):
    """Price is a soft filter — a listing with no stated price still
    shows up here, but was never actually confirmed to be in budget."""
    with store.connect() as conn:
        listing = Listing(
            post_url="https://facebook.com/groups/1/posts/6",
            group_name="Secret Tel Aviv",
            raw_text="raw text",
            price=None,
            score=80,
        )
        store.insert_listing(conn, listing, matched_profiles=["default"])
        page = dashboard.render_page(conn, "tok")
    assert '<span class="potential">potential</span>' in page


def test_render_page_omits_potential_badge_when_price_is_known(isolated_db):
    with store.connect() as conn:
        _seed(conn)  # price=3300
        page = dashboard.render_page(conn, "tok")
    assert '<span class="potential">potential</span>' not in page


def test_render_page_includes_google_maps_link_for_known_address(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)  # has address="דיזנגוף 120"
        page = dashboard.render_page(conn, "tok")
    assert "Google Maps" in page
    assert "google.com/maps" in page
    assert listing.post_url in page  # "View post" link still present too


def test_render_page_outbound_card_links_never_leak_the_token_via_referer(isolated_db):
    """Every outbound card link (post + Google Maps) must carry
    rel="noreferrer" — the page's own URL carries ?token=<DASHBOARD_TOKEN>,
    the dashboard's only auth mechanism, and a browser sends the current
    page URL as Referer by default."""
    with store.connect() as conn:
        listing = Listing(
            post_url="https://facebook.com/groups/1/posts/1",
            group_name="Secret Tel Aviv",
            raw_text="raw text",
            price=3300,
            address="דיזנגוף 120",
            score=80,
        )
        store.insert_listing(conn, listing, matched_profiles=["default"])
        page = dashboard.render_page(conn, "tok")
    outbound_hrefs = [
        line
        for line in page.splitlines()
        if 'target="_blank"' in line and ("facebook.com" in line or "google.com/maps" in line)
    ]
    assert outbound_hrefs  # sanity: the page actually has outbound links to check
    assert all('rel="noreferrer"' in line for line in outbound_hrefs)


def test_map_popup_links_also_carry_noreferrer():
    """Same token-leak concern applies to the Leaflet popup links, which
    are built in JS rather than embedded directly in the HTML."""
    assert 'href="\' + m.post_url + \'" target="_blank" rel="noreferrer"' in (
        dashboard._MAP_SCRIPT_TEMPLATE
    )
    assert 'rel="noreferrer">Google Maps</a>' in dashboard._MAP_SCRIPT_TEMPLATE


def test_render_page_omits_google_maps_link_without_address_or_coordinates(isolated_db):
    with store.connect() as conn:
        listing = Listing(
            post_url="https://facebook.com/groups/1/posts/6",
            group_name="Secret Tel Aviv",
            raw_text="raw text",
            price=3300,
            score=80,
        )
        store.insert_listing(conn, listing, matched_profiles=["default"])
        page = dashboard.render_page(conn, "tok")
    assert "Google Maps" not in page


def test_render_page_escapes_script_breakout_in_marker_json(isolated_db):
    with store.connect() as conn:
        listing = Listing(
            post_url="https://facebook.com/groups/1/posts/7",
            group_name="Secret Tel Aviv",
            raw_text="raw text",
            price=3300,
            address="דיזנגוף 120",
            lat=32.0768,
            lon=34.7742,
            summary="nice place</script><script>alert(1)</script>",
            score=80,
        )
        store.insert_listing(conn, listing, matched_profiles=["default"])
        page = dashboard.render_page(conn, "tok")
    assert "</script><script>alert(1)</script>" not in page


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


# --- _vote_form: renders a POST form, not a mutating GET link ---


def test_vote_form_is_a_post_form_with_the_right_hidden_fields():
    html_out = dashboard._vote_form("tok", "https://fb.com/1", "dismiss", "🗑 Dismiss")
    assert '<form method="post" action="/vote"' in html_out
    assert 'name="token" value="tok"' in html_out
    assert 'name="action" value="dismiss"' in html_out
    assert 'name="post" value="https://fb.com/1"' in html_out
    assert 'href="/vote' not in html_out  # never a GET link


# --- /vote: POST-only, so a leaked link can't be silently exploited ---


@contextmanager
def _running_dashboard(token: str):
    server = HTTPServer(("127.0.0.1", 0), dashboard.make_handler(token))
    port = server.server_address[1]
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()
        t.join(timeout=5)


def test_vote_get_returns_405_and_does_not_mutate(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)
    with _running_dashboard("tok") as base_url:
        req = urllib.request.Request(
            f"{base_url}/vote?token=tok&action=dismiss&post={listing.post_url}"
        )
        try:
            urllib.request.urlopen(req, timeout=5)
            raised = None
        except urllib.error.HTTPError as exc:
            raised = exc.code
    assert raised == 405
    with store.connect() as conn:
        assert store.is_dismissed(conn, listing.post_url) is False


def test_vote_post_with_correct_token_dismisses_the_listing(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)
    with _running_dashboard("tok") as base_url:
        body = f"token=tok&action=dismiss&post={listing.post_url}".encode()
        req = urllib.request.Request(f"{base_url}/vote", data=body, method="POST")
        resp = urllib.request.urlopen(req, timeout=5)
        # urlopen follows the 302 automatically, landing back on the main
        # page — the meaningful check is the DB mutation below.
        assert resp.status == 200
        assert "token=tok" in resp.geturl()
    with store.connect() as conn:
        assert store.is_dismissed(conn, listing.post_url) is True


def test_vote_post_with_wrong_token_is_forbidden_and_does_not_mutate(isolated_db):
    with store.connect() as conn:
        listing = _seed(conn)
    with _running_dashboard("tok") as base_url:
        body = f"token=wrong&action=dismiss&post={listing.post_url}".encode()
        req = urllib.request.Request(f"{base_url}/vote", data=body, method="POST")
        try:
            urllib.request.urlopen(req, timeout=5)
            raised = None
        except urllib.error.HTTPError as exc:
            raised = exc.code
    assert raised == 403
    with store.connect() as conn:
        assert store.is_dismissed(conn, listing.post_url) is False
