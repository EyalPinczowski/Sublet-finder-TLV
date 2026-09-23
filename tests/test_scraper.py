import os
import subprocess
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest

from src import scraper
from src.config import FacebookGroup


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


def test_run_lock_does_not_reclaim_a_fresh_lock_from_a_live_pid(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    proc = subprocess.Popen(["sleep", "5"])
    try:
        scraper.LOCK_PATH.write_text(str(proc.pid))  # fresh mtime — not stale
        with pytest.raises(scraper.ScanAlreadyRunning):
            with scraper.run_lock():
                pass
    finally:
        proc.kill()
        proc.wait()


def test_run_lock_reclaims_and_terminates_a_wedged_but_still_alive_process(tmp_path, monkeypatch):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    monkeypatch.setattr(scraper, "_STALE_LOCK_MAX_AGE_SECONDS", 0)  # anything counts as stale
    proc = subprocess.Popen(["sleep", "30"])
    try:
        scraper.LOCK_PATH.write_text(str(proc.pid))
        old = time.time() - 100
        os.utime(scraper.LOCK_PATH, (old, old))
        with scraper.run_lock():
            assert int(scraper.LOCK_PATH.read_text()) == os.getpid()
        proc.wait(timeout=5)
        assert proc.poll() is not None  # the wedged process was terminated, not just ignored
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


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


def test_post_timestamp_skips_waiting_calls_when_locator_finds_nothing():
    """count()==0 must return immediately rather than calling
    get_attribute()/inner_text() and waiting out their timeout hoping a
    matching element eventually appears."""
    article = MagicMock()
    time_loc = MagicMock()
    time_loc.count.return_value = 0
    article.locator.return_value = time_loc
    assert scraper._post_timestamp(article) is None
    time_loc.first.get_attribute.assert_not_called()


# --- _extract_one_post: author/permalink locators are count()-checked ---


def _make_article(text="post text", author_count=0, author_text="", permalink_count=0, href=""):
    article = MagicMock()
    article.inner_text.return_value = text
    author_loc = MagicMock()
    author_loc.count.return_value = author_count
    author_loc.first.inner_text.return_value = author_text
    permalink_loc = MagicMock()
    permalink_loc.count.return_value = permalink_count
    permalink_loc.first.get_attribute.return_value = href

    def locator_side_effect(selector):
        if selector == "h3 a, h2 a, strong a":
            return author_loc
        if selector == 'a[href*="/posts/"], a[href*="/permalink/"]':
            return permalink_loc
        return MagicMock(count=MagicMock(return_value=0))

    article.locator.side_effect = locator_side_effect
    return article, author_loc, permalink_loc


def test_extract_one_post_uses_author_and_permalink_when_present(monkeypatch):
    monkeypatch.setattr(scraper, "_post_timestamp", lambda article: None)
    monkeypatch.setattr(scraper, "_images", lambda article: [])
    article, _, _ = _make_article(
        text="סאבלט בפלורנטין",
        author_count=1,
        author_text="Dana",
        permalink_count=1,
        href="https://fb.com/groups/1/posts/1",
    )
    post = scraper._extract_one_post(article)
    assert post.author == "Dana"
    assert post.post_url == "https://fb.com/groups/1/posts/1"


def test_extract_one_post_falls_back_to_text_sig_without_a_permalink(monkeypatch):
    monkeypatch.setattr(scraper, "_post_timestamp", lambda article: None)
    monkeypatch.setattr(scraper, "_images", lambda article: [])
    article, _, _ = _make_article(text="סאבלט בפלורנטין", author_count=0, permalink_count=0)
    post = scraper._extract_one_post(article)
    assert post.post_url.startswith("text:")
    assert post.author == ""


def test_extract_one_post_skips_waiting_calls_when_neither_locator_matches(monkeypatch):
    monkeypatch.setattr(scraper, "_post_timestamp", lambda article: None)
    monkeypatch.setattr(scraper, "_images", lambda article: [])
    article, author_loc, permalink_loc = _make_article(text="t", author_count=0, permalink_count=0)
    scraper._extract_one_post(article)
    author_loc.first.inner_text.assert_not_called()
    permalink_loc.first.get_attribute.assert_not_called()


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
    """A page whose [role="article"] locator reports a fixed count, and
    whose _blocked_reason() probes (login-form inputs) always report
    "not present" — otherwise a bare page.locator(...).count.return_value
    would apply to EVERY selector, including the login-form check
    _scroll_and_extract now runs each iteration, causing a false-positive
    ScraperBlocked on every test using this helper."""
    page = MagicMock()
    page.url = "https://www.facebook.com/groups/1"

    def locator_side_effect(selector):
        loc = MagicMock()
        loc.count.return_value = count if selector == '[role="article"]' else 0
        return loc

    page.locator.side_effect = locator_side_effect
    return page


def test_scroll_and_extract_stops_at_limit(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(100)
    posts = iter(
        scraper.RawPost(post_url=f"https://fb.com/{i}", author="a", text="t") for i in range(10)
    )
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: next(posts))
    result, saw_any_article = scraper._scroll_and_extract(
        page, "g1", limit=5, cutoff=None, max_scrolls=15
    )
    assert len(result) == 5
    assert saw_any_article is True


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
    result, _ = scraper._scroll_and_extract(page, "g1", limit=100, cutoff=cutoff, max_scrolls=15)
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
    result, _ = scraper._scroll_and_extract(page, "g1", limit=100, cutoff=cutoff, max_scrolls=15)
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
    result, _ = scraper._scroll_and_extract(page, "g1", limit=10, cutoff=cutoff, max_scrolls=15)
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
    result, _ = scraper._scroll_and_extract(page, "g1", limit=10, cutoff=None, max_scrolls=15)
    assert len(result) == 10


def test_scroll_and_extract_respects_max_scrolls_cap(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(2)  # the DOM never grows past 2 articles
    single_post = scraper.RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: single_post)
    result, _ = scraper._scroll_and_extract(page, "g1", limit=100, cutoff=None, max_scrolls=3)
    assert len(result) == 1  # never reaches `limit`; terminates via max_scrolls, not a hang


def test_scroll_and_extract_reports_no_articles_seen_when_feed_renders_empty(monkeypatch):
    """The soft-block signal cli.py's cross-group escalation relies on:
    zero [role="article"] matches for the whole scroll pass, distinct from
    zero *results* (which just means nothing new since the cutoff)."""
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = _fixed_count_page(0)
    result, saw_any_article = scraper._scroll_and_extract(
        page, "g1", limit=10, cutoff=None, max_scrolls=3
    )
    assert result == []
    assert saw_any_article is False


def test_scroll_and_extract_detects_a_mid_session_checkpoint(monkeypatch):
    """A checkpoint appearing partway through scrolling (not just before
    the first scroll) must still raise ScraperBlocked, not silently keep
    scrolling a checkpoint page."""
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    page = MagicMock()
    page.url = "https://www.facebook.com/groups/1"
    counts = iter([1, 2])  # simulates one more article loading in per scroll

    def locator_side_effect(selector):
        loc = MagicMock()
        loc.count.return_value = next(counts, 2) if selector == '[role="article"]' else 0
        return loc

    page.locator.side_effect = locator_side_effect

    call_count = {"n": 0}

    def fake_blocked_reason(_page):
        call_count["n"] += 1
        return None if call_count["n"] == 1 else "checkpoint appeared"

    monkeypatch.setattr(scraper, "_blocked_reason", fake_blocked_reason)
    snapshot_calls = []
    monkeypatch.setattr(
        scraper, "_save_checkpoint_snapshot", lambda name, p: snapshot_calls.append(name)
    )
    posts = iter([scraper.RawPost(post_url="https://fb.com/1", author="a", text="t")])
    monkeypatch.setattr(scraper, "_extract_one_post", lambda article: next(posts))

    with pytest.raises(scraper.ScraperBlocked):
        scraper._scroll_and_extract(page, "g1", limit=100, cutoff=None, max_scrolls=15)
    assert snapshot_calls == ["g1"]


# --- scrape_group: context-based session (one page per group, shared context) ---


def test_scrape_group_closes_its_page_on_success(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    monkeypatch.setattr(scraper, "_blocked_reason", lambda page: None)
    monkeypatch.setattr(scraper, "_force_chronological_sort", lambda page: True)
    monkeypatch.setattr(scraper, "_scroll_and_extract", lambda *a, **k: ([], True))
    context = MagicMock()
    group = FacebookGroup(name="g1", url="https://facebook.com/groups/1")
    result, saw_any_article = scraper.scrape_group(context, group, limit=10)
    assert result == []
    assert saw_any_article is True
    context.new_page.return_value.close.assert_called_once()


def test_scrape_group_closes_its_page_even_when_blocked(monkeypatch):
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    monkeypatch.setattr(scraper, "_blocked_reason", lambda page: "blocked!")
    monkeypatch.setattr(scraper, "_save_checkpoint_snapshot", lambda name, page: None)
    context = MagicMock()
    group = FacebookGroup(name="g1", url="https://facebook.com/groups/1")
    with pytest.raises(scraper.ScraperBlocked):
        scraper.scrape_group(context, group, limit=10)
    context.new_page.return_value.close.assert_called_once()


def test_scrape_group_does_not_open_its_own_browser_session(monkeypatch):
    """scrape_group must use the context it's handed, never open its own
    Playwright session — that's browser.open_scan_session's job now,
    shared across the whole scan."""
    monkeypatch.setattr(scraper, "_jitter", lambda *_: None)
    monkeypatch.setattr(scraper, "_blocked_reason", lambda page: None)
    monkeypatch.setattr(scraper, "_force_chronological_sort", lambda page: True)
    monkeypatch.setattr(scraper, "_scroll_and_extract", lambda *a, **k: ([], True))
    context = MagicMock()
    group = FacebookGroup(name="g1", url="https://facebook.com/groups/1")
    scraper.scrape_group(context, group, limit=10)
    context.new_page.assert_called_once()


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
