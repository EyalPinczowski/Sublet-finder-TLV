import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src import scraper


def test_text_sig_is_stable_for_same_text():
    a = scraper._text_sig("סאבלט בפלורנטין, 4500 שקל")
    b = scraper._text_sig("סאבלט בפלורנטין, 4500 שקל")
    assert a == b
    assert a.startswith("text:")


def test_text_sig_differs_for_different_text():
    a = scraper._text_sig("סאבלט בפלורנטין")
    b = scraper._text_sig("סאבלט ברוטשילד")
    assert a != b


def test_text_sig_ignores_whitespace_differences():
    a = scraper._text_sig("hello   world")
    b = scraper._text_sig("hello world")
    assert a == b


def _make_page(url="https://facebook.com/groups/1", has_login_form=False):
    page = MagicMock()
    page.url = url
    if has_login_form:
        page.locator.return_value.count.return_value = 1
    else:
        page.locator.return_value.count.return_value = 0
    return page


def test_blocked_reason_none_for_normal_group_page():
    page = _make_page("https://www.facebook.com/groups/1")
    assert scraper._blocked_reason(page) is None


def test_blocked_reason_detects_checkpoint_url():
    page = _make_page("https://www.facebook.com/checkpoint/?next=...")
    assert scraper._blocked_reason(page) is not None


def test_blocked_reason_detects_login_redirect():
    page = _make_page("https://www.facebook.com/login.php")
    assert scraper._blocked_reason(page) is not None


def test_blocked_reason_detects_login_form():
    page = _make_page("https://www.facebook.com/groups/1", has_login_form=True)
    assert scraper._blocked_reason(page) is not None


def test_run_lock_prevents_concurrent_scans(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    with scraper.run_lock():
        with pytest.raises(scraper.ScanAlreadyRunning):
            with scraper.run_lock():
                pass


def test_run_lock_releases_after_use(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    with scraper.run_lock():
        pass
    assert not scraper.LOCK_PATH.exists()
    with scraper.run_lock():  # does not raise — the lock was released
        pass


def test_run_lock_reclaims_a_stale_lock_from_a_dead_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    # A pid that (almost certainly) isn't running.
    dead_pid = 2**30
    scraper.LOCK_PATH.write_text(str(dead_pid))
    with scraper.run_lock():
        assert int(scraper.LOCK_PATH.read_text()) == os.getpid()


# --- relative/absolute timestamp parsing ---

_NOW = datetime(2026, 9, 23, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "text,expected_delta",
    [
        ("2 hrs", timedelta(hours=2)),
        ("2 hours ago", timedelta(hours=2)),
        ("an hour ago", timedelta(hours=1)),
        ("5 mins", timedelta(minutes=5)),
        ("a minute ago", timedelta(minutes=1)),
        ("3 d", timedelta(days=3)),
        ("3 days ago", timedelta(days=3)),
        ("Yesterday", timedelta(days=1)),
        ("Just now", timedelta(seconds=0)),
        ("2 weeks ago", timedelta(weeks=2)),
        ("לפני שעה", timedelta(hours=1)),
        ("לפני 3 שעות", timedelta(hours=3)),
        ("לפני דקה", timedelta(minutes=1)),
        ("לפני 10 דקות", timedelta(minutes=10)),
        ("לפני יום", timedelta(days=1)),
        ("לפני 4 ימים", timedelta(days=4)),
        ("אתמול", timedelta(days=1)),
        ("עכשיו", timedelta(seconds=0)),
    ],
)
def test_parse_relative_timestamp_known_formats(text, expected_delta):
    assert scraper._parse_relative_timestamp(text, now=_NOW) == _NOW - expected_delta


def test_parse_relative_timestamp_unparseable_returns_none():
    assert scraper._parse_relative_timestamp("some random caption", now=_NOW) is None


def test_parse_relative_timestamp_empty_returns_none():
    assert scraper._parse_relative_timestamp("", now=_NOW) is None


def test_parse_absolute_timestamp_iso8601():
    dt = scraper._parse_absolute_timestamp("2026-09-20T10:30:00")
    assert dt == datetime(2026, 9, 20, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_absolute_timestamp_iso8601_with_z_suffix():
    dt = scraper._parse_absolute_timestamp("2026-09-20T10:30:00Z")
    assert dt == datetime(2026, 9, 20, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_absolute_timestamp_long_form():
    dt = scraper._parse_absolute_timestamp("September 20, 2026 at 10:30 AM")
    assert dt == datetime(2026, 9, 20, 10, 30, 0, tzinfo=timezone.utc)


def test_parse_absolute_timestamp_garbage_returns_none():
    assert scraper._parse_absolute_timestamp("not a date at all") is None


def test_parse_absolute_timestamp_empty_returns_none():
    assert scraper._parse_absolute_timestamp("") is None


# --- _post_timestamp: locator-based, defensive ---


def _make_time_locator(title=None, aria_label=None, text=""):
    def get_attr(name, timeout=None):
        if name == "title":
            return title
        if name == "aria-label":
            return aria_label
        return None

    time_el = MagicMock()
    time_el.get_attribute.side_effect = get_attr
    time_el.inner_text.return_value = text
    loc = MagicMock()
    loc.first = time_el
    return loc


def test_post_timestamp_uses_absolute_attribute_when_present():
    article = MagicMock()
    article.locator.return_value = _make_time_locator(title="2026-09-20T10:30:00Z")
    dt = scraper._post_timestamp(article)
    assert dt == datetime(2026, 9, 20, 10, 30, 0, tzinfo=timezone.utc)


def test_post_timestamp_falls_back_to_relative_text():
    article = MagicMock()
    article.locator.return_value = _make_time_locator(text="2 hrs")
    dt = scraper._post_timestamp(article)
    assert dt is not None


def test_post_timestamp_none_when_locator_raises():
    article = MagicMock()
    article.locator.side_effect = Exception("boom")
    assert scraper._post_timestamp(article) is None


def test_post_timestamp_none_when_nothing_parseable():
    article = MagicMock()
    article.locator.return_value = _make_time_locator(text="unrecognizable caption")
    assert scraper._post_timestamp(article) is None


# --- _force_chronological_sort ---


def test_force_chronological_sort_success():
    page = MagicMock()
    assert scraper._force_chronological_sort(page) is True


def test_force_chronological_sort_returns_false_on_failure():
    page = MagicMock()
    page.get_by_role.side_effect = Exception("sort control not found")
    assert scraper._force_chronological_sort(page) is False


# --- _scroll_and_extract: cutoff-aware scroll/stop logic ---


def _fixed_count_page(count: int) -> MagicMock:
    page = MagicMock()
    page.locator.return_value.count.return_value = count
    return page


def test_scroll_and_extract_stops_at_limit(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(100)
    posts = iter(
        scraper.RawPost(post_url=f"https://fb.com/{i}", author="a", text="t") for i in range(10)
    )
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: next(posts))
    result = scraper._scroll_and_extract(page, limit=5, cutoff=None, max_scrolls=15)
    assert len(result) == 5


def test_scroll_and_extract_stops_on_consecutive_old_posts(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(100)
    cutoff = _NOW - timedelta(hours=1)
    old = _NOW - timedelta(hours=5)
    posts = iter(
        [
            scraper.RawPost(post_url="https://fb.com/1", author="a", text="t", posted_at=_NOW),
            scraper.RawPost(post_url="https://fb.com/2", author="a", text="t", posted_at=_NOW),
            scraper.RawPost(post_url="https://fb.com/o1", author="a", text="t", posted_at=old),
            scraper.RawPost(post_url="https://fb.com/o2", author="a", text="t", posted_at=old),
            scraper.RawPost(post_url="https://fb.com/o3", author="a", text="t", posted_at=old),
            scraper.RawPost(
                post_url="https://fb.com/never-reached", author="a", text="t", posted_at=_NOW
            ),
        ]
    )
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: next(posts))
    result = scraper._scroll_and_extract(page, limit=100, cutoff=cutoff, max_scrolls=15)
    assert [p.post_url for p in result] == [
        "https://fb.com/1",
        "https://fb.com/2",
        "https://fb.com/o1",
        "https://fb.com/o2",
        "https://fb.com/o3",
    ]


def test_scroll_and_extract_resets_consecutive_old_counter_on_a_new_post(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(100)
    cutoff = _NOW - timedelta(hours=1)
    old = _NOW - timedelta(hours=5)
    posts = iter(
        [
            scraper.RawPost(post_url="https://fb.com/1", author="a", text="t", posted_at=old),
            scraper.RawPost(post_url="https://fb.com/2", author="a", text="t", posted_at=old),
            scraper.RawPost(post_url="https://fb.com/3", author="a", text="t", posted_at=_NOW),
            scraper.RawPost(post_url="https://fb.com/4", author="a", text="t", posted_at=old),
            scraper.RawPost(post_url="https://fb.com/5", author="a", text="t", posted_at=old),
            scraper.RawPost(post_url="https://fb.com/6", author="a", text="t", posted_at=old),
        ]
    )
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: next(posts))
    result = scraper._scroll_and_extract(page, limit=100, cutoff=cutoff, max_scrolls=15)
    assert len(result) == 6  # the post at #3 reset the counter, so #4-6 are needed to stop


def test_scroll_and_extract_unknown_age_never_triggers_stop(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(100)
    cutoff = _NOW - timedelta(hours=1)
    posts = iter(
        scraper.RawPost(post_url=f"https://fb.com/{i}", author="a", text="t", posted_at=None)
        for i in range(10)
    )
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: next(posts))
    result = scraper._scroll_and_extract(page, limit=10, cutoff=cutoff, max_scrolls=15)
    assert len(result) == 10


def test_scroll_and_extract_cutoff_none_disables_age_based_stopping(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(100)
    very_old = _NOW - timedelta(days=30)
    posts = iter(
        scraper.RawPost(post_url=f"https://fb.com/{i}", author="a", text="t", posted_at=very_old)
        for i in range(10)
    )
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: next(posts))
    result = scraper._scroll_and_extract(page, limit=10, cutoff=None, max_scrolls=15)
    assert len(result) == 10


def test_scroll_and_extract_respects_max_scrolls_cap(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(2)  # the DOM never grows past 2 articles
    single_post = scraper.RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: single_post)
    result = scraper._scroll_and_extract(page, limit=100, cutoff=None, max_scrolls=3)
    assert len(result) == 1  # never reaches `limit`; terminates via max_scrolls, not a hang


# --- checkpoint debug screenshot ---


def test_save_checkpoint_snapshot_never_raises_on_screenshot_failure():
    page = MagicMock()
    page.screenshot.side_effect = Exception("boom")
    scraper._save_checkpoint_snapshot("Some Group Name", page)  # must not raise


def test_save_checkpoint_snapshot_sanitizes_the_group_name_in_the_path():
    page = MagicMock()
    scraper._save_checkpoint_snapshot("Some Group! Name", page)
    path = page.screenshot.call_args.kwargs["path"]
    assert path.endswith(".png")
    assert "!" not in path
    assert " " not in path
