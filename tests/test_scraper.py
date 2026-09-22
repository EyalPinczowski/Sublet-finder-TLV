import os
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
