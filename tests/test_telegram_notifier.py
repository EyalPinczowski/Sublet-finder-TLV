from datetime import date
from unittest.mock import MagicMock, patch

import requests

from src.config import SearchConfig
from src.listing_models import Listing
from src.telegram_notifier import format_alert, send_listing, send_text


def make_listing(**overrides) -> Listing:
    defaults = dict(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="Secret Tel Aviv",
        raw_text="raw text here",
        price=3300,
        rooms=3.0,
        roommates=2,
        toilets=2,
        address="דיזנגוף 120",
        phone="050-1234567",
        summary="A nice sublet near Dizengoff",
        score=80,
    )
    defaults.update(overrides)
    return Listing(**defaults)


def make_profile(**overrides) -> SearchConfig:
    defaults = dict(name="single room", emoji="\U0001F7E2")
    defaults.update(overrides)
    return SearchConfig(**defaults)


def test_format_alert_includes_key_fields():
    listing = make_listing()
    text = format_alert(listing, make_profile(), 80)
    assert "3300" in text
    assert "3.0 rooms" in text
    assert "2 roommates" in text
    assert "2 bathrooms" in text
    assert "דיזנגוף 120" in text
    assert "050-1234567" in text
    assert listing.post_url in text
    assert "wa.me/972501234567" in text
    assert "google.com/maps" in text
    assert listing.summary in text


def test_format_alert_shows_profile_emoji_and_name():
    profile = make_profile(name="two rooms (with a friend)", emoji="\U0001F535")
    text = format_alert(make_listing(), profile, 80)
    assert "\U0001F535" in text
    assert "two rooms (with a friend)" in text


def test_format_alert_shows_available_rooms():
    listing = make_listing(available_rooms=2)
    assert "2 room(s) available now" in format_alert(listing, make_profile(), 80)


def test_format_alert_shows_price_not_listed_when_missing():
    listing = make_listing(price=None)
    text = format_alert(listing, make_profile(), 80)
    assert "Price not listed" in text
    assert "None ILS" not in text


def test_format_alert_shows_price_when_known():
    listing = make_listing(price=3300)
    text = format_alert(listing, make_profile(), 80)
    assert "3300 ILS" in text
    assert "Price not listed" not in text


def test_format_alert_shows_lease_start_and_duration():
    listing = make_listing(lease_start_date=date(2026, 11, 1), lease_duration_days=14)
    text = format_alert(listing, make_profile(), 80)
    assert "2026-11-01" in text
    assert "14 days" in text


def test_format_alert_uses_given_score_not_listing_score():
    # score is passed explicitly per profile, since the same listing can
    # score differently under two profiles with different price ranges —
    # listing.score (used for DB sorting) must not leak into the alert text.
    listing = make_listing(score=999)
    text = format_alert(listing, make_profile(), 42)
    assert "(42)" in text
    assert "(999)" not in text


def test_format_alert_omits_post_link_for_synthetic_key():
    listing = make_listing(post_url="text:abcd1234")
    text = format_alert(listing, make_profile(), 80)
    assert "text:abcd1234" not in text


def test_format_alert_shows_distance_when_geocoded():
    listing = make_listing(distance_m=350.4)
    assert "350m from target zone" in format_alert(listing, make_profile(), 80)


def _mock_response(ok=True, status_code=200, retry_after=None):
    resp = MagicMock()
    resp.status_code = status_code
    if status_code == 200:
        resp.raise_for_status.return_value = None
    else:
        resp.raise_for_status.side_effect = requests.exceptions.HTTPError(f"HTTP {status_code}")
    body = {"ok": ok}
    if retry_after is not None:
        body["parameters"] = {"retry_after": retry_after}
    resp.json.return_value = body
    resp.headers = {}
    return resp


def test_send_text_returns_true_on_ok():
    with patch("src.telegram_notifier._session.post", return_value=_mock_response(True)):
        assert send_text("token", "chat", "hello") is True


def test_send_text_returns_false_when_not_ok():
    with patch("src.telegram_notifier._session.post", return_value=_mock_response(False)):
        assert send_text("token", "chat", "hello") is False


def test_send_text_returns_false_on_request_failure():
    with patch("src.telegram_notifier._session.post", side_effect=Exception("network down")):
        assert send_text("token", "chat", "hello") is False


def test_send_text_retries_once_after_a_429_then_succeeds(monkeypatch):
    sleep_calls = []
    monkeypatch.setattr("src.telegram_notifier.time.sleep", lambda s: sleep_calls.append(s))
    responses = iter([_mock_response(status_code=429, retry_after=2), _mock_response(ok=True)])
    with patch(
        "src.telegram_notifier._session.post", side_effect=lambda *a, **k: next(responses)
    ) as mock_post:
        assert send_text("token", "chat", "hello") is True
    assert mock_post.call_count == 2
    assert sleep_calls == [2.0]


def test_send_text_gives_up_after_a_second_429(monkeypatch):
    monkeypatch.setattr("src.telegram_notifier.time.sleep", lambda s: None)
    responses = iter(
        [
            _mock_response(status_code=429, retry_after=1),
            _mock_response(status_code=429, retry_after=1),
        ]
    )
    with patch(
        "src.telegram_notifier._session.post", side_effect=lambda *a, **k: next(responses)
    ) as mock_post:
        assert send_text("token", "chat", "hello") is False
    assert mock_post.call_count == 2  # exactly one retry, never an infinite loop


def test_send_listing_plain_text_when_no_images():
    listing = make_listing(images=[])
    with patch(
        "src.telegram_notifier._session.post", return_value=_mock_response(True)
    ) as mock_post:
        assert send_listing("token", "chat", listing, make_profile(), 80) is True
        assert mock_post.call_count == 1
        assert "sendMessage" in mock_post.call_args.args[0]


def test_send_listing_sends_single_photo():
    listing = make_listing(images=["https://example.com/a.jpg"])
    with patch(
        "src.telegram_notifier._session.post", return_value=_mock_response(True)
    ) as mock_post:
        assert send_listing("token", "chat", listing, make_profile(), 80) is True
        assert mock_post.call_count == 1
        assert "sendPhoto" in mock_post.call_args.args[0]


def test_send_listing_falls_back_to_text_when_photo_fails():
    listing = make_listing(images=["https://example.com/a.jpg"])
    responses = [_mock_response(False), _mock_response(True)]
    with patch("src.telegram_notifier._session.post", side_effect=responses) as mock_post:
        assert send_listing("token", "chat", listing, make_profile(), 80) is True
        methods = [call.args[0] for call in mock_post.call_args_list]
        assert any("sendPhoto" in m for m in methods)
        assert any("sendMessage" in m for m in methods)


def test_send_listing_sends_album_for_multiple_photos():
    listing = make_listing(images=["https://example.com/a.jpg", "https://example.com/b.jpg"])
    with patch(
        "src.telegram_notifier._session.post", return_value=_mock_response(True)
    ) as mock_post:
        assert send_listing("token", "chat", listing, make_profile(), 80) is True
        assert "sendMediaGroup" in mock_post.call_args_list[0].args[0]


def test_send_listing_falls_back_to_text_when_all_sends_fail():
    listing = make_listing(images=[])
    with patch("src.telegram_notifier._session.post", return_value=_mock_response(False)):
        assert send_listing("token", "chat", listing, make_profile(), 80) is False


def test_send_listing_includes_vote_buttons_when_conn_given(isolated_db):
    from src import store

    listing = make_listing(images=[])
    with store.connect() as conn:
        with patch(
            "src.telegram_notifier._session.post", return_value=_mock_response(True)
        ) as mock_post:
            send_listing("token", "chat", listing, make_profile(), 80, conn=conn)
            payload = mock_post.call_args.kwargs["json"]
            assert "reply_markup" in payload
            assert "save|" in str(payload["reply_markup"])
