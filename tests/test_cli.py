from datetime import datetime, timedelta, timezone

import pytest

from src import cli, scan_state, scraper, store
from src.config import (
    Config,
    FacebookGroup,
    LLMConfig,
    ScanWindowConfig,
    SearchConfig,
    StayConfig,
    ZoneConfig,
)
from src.listing_models import Listing
from src.scraper import RawPost, ScraperBlocked


def make_config(**overrides) -> Config:
    defaults = dict(
        facebook_groups=[FacebookGroup(name="g1", url="https://facebook.com/groups/1")],
        posts_per_group=10,
        searches=[SearchConfig(name="default")],
        telegram=None,
        llm=LLMConfig(enabled=False),
        zone=ZoneConfig(),
        stay=StayConfig(),
        scan_window=ScanWindowConfig(initial_lookback_days=4),
    )
    defaults.update(overrides)
    return Config(**defaults)


class _Args:
    def __init__(self, headed=False, dry_run=False):
        self.headed = headed
        self.dry_run = dry_run


# --- _compute_cutoff ---


def test_compute_cutoff_first_run_uses_initial_lookback(monkeypatch):
    monkeypatch.setattr(scan_state, "load_last_scan_completed_at", lambda: None)
    config = make_config(scan_window=ScanWindowConfig(initial_lookback_days=4))
    expected_floor = datetime.now(timezone.utc) - timedelta(days=4)
    cutoff = cli._compute_cutoff(config)
    assert abs((cutoff - expected_floor).total_seconds()) < 5


def test_compute_cutoff_normal_operation_uses_last_scan(monkeypatch):
    last = datetime.now(timezone.utc) - timedelta(hours=12)
    monkeypatch.setattr(scan_state, "load_last_scan_completed_at", lambda: last)
    config = make_config(scan_window=ScanWindowConfig(initial_lookback_days=4))
    assert cli._compute_cutoff(config) == last


def test_compute_cutoff_caps_a_long_outage_at_initial_lookback(monkeypatch):
    long_ago = datetime.now(timezone.utc) - timedelta(days=30)
    monkeypatch.setattr(scan_state, "load_last_scan_completed_at", lambda: long_ago)
    config = make_config(scan_window=ScanWindowConfig(initial_lookback_days=4))
    cutoff = cli._compute_cutoff(config)
    floor = datetime.now(timezone.utc) - timedelta(days=4)
    assert abs((cutoff - floor).total_seconds()) < 5
    assert cutoff > long_ago


# --- _scan: scan-state write only on a clean, unblocked completion ---


def test_scan_records_completion_when_all_groups_succeed(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "_prune_dead_links", lambda conn, headless: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: [])
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    recorded = []
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: recorded.append(True))
    config = make_config(
        facebook_groups=[
            FacebookGroup(name="g1", url="https://facebook.com/groups/1"),
            FacebookGroup(name="g2", url="https://facebook.com/groups/2"),
        ]
    )
    blocked = cli._scan(config, _Args())
    assert blocked is False
    assert recorded == [True]


def test_scan_skips_recording_when_a_group_is_blocked(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "_prune_dead_links", lambda conn, headless: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli.random, "shuffle", lambda seq: None)  # deterministic order

    def fake_scrape(group, **kwargs):
        if group.name == "g1":
            return []
        raise ScraperBlocked("g2: checkpoint")

    monkeypatch.setattr(cli, "scrape_group", fake_scrape)
    recorded = []
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: recorded.append(True))
    config = make_config(
        facebook_groups=[
            FacebookGroup(name="g1", url="https://facebook.com/groups/1"),
            FacebookGroup(name="g2", url="https://facebook.com/groups/2"),
        ]
    )
    blocked = cli._scan(config, _Args())
    assert blocked is True
    assert recorded == []


def test_scan_passes_computed_cutoff_to_scrape_group(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "_prune_dead_links", lambda conn, headless: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    expected_cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    monkeypatch.setattr(cli, "_compute_cutoff", lambda config: expected_cutoff)
    seen_cutoffs = []

    def fake_scrape(group, limit, cutoff, headless):
        seen_cutoffs.append(cutoff)
        return []

    monkeypatch.setattr(cli, "scrape_group", fake_scrape)
    cli._scan(make_config(), _Args())
    assert seen_cutoffs == [expected_cutoff]


def test_cmd_scan_exits_2_when_blocked(isolated_db, monkeypatch, tmp_path):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    monkeypatch.setattr(cli, "load_config", lambda: make_config())
    monkeypatch.setattr(cli, "_scan", lambda config, args: True)
    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_scan(_Args())
    assert exc_info.value.code == 2


def test_cmd_scan_does_not_exit_when_not_blocked(isolated_db, monkeypatch, tmp_path):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    monkeypatch.setattr(cli, "load_config", lambda: make_config())
    monkeypatch.setattr(cli, "_scan", lambda config, args: False)
    cli.cmd_scan(_Args())  # must not raise SystemExit


# --- _prune_dead_links: safe no-op when there's nothing to check ---


def test_prune_dead_links_noop_when_no_matched_listings(isolated_db):
    with store.connect() as conn:
        cli._prune_dead_links(conn, headless=True)  # must not raise


# --- freshness scoring: post.posted_at must actually reach scoring.score ---


def test_scan_threads_post_age_into_scoring(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "_prune_dead_links", lambda conn, headless: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    posted_at = datetime.now(timezone.utc) - timedelta(hours=5)
    post = RawPost(post_url="https://fb.com/1", author="a", text="t", posted_at=posted_at)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: [post])

    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t")
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    monkeypatch.setattr(cli, "matches_search", lambda *a, **k: True)

    captured_age_hours = []

    def fake_score(listing_arg, profile, zone_cfg, age_hours=None):
        captured_age_hours.append(age_hours)
        return 50

    monkeypatch.setattr(cli.scoring, "score", fake_score)

    cli._scan(make_config(), _Args())

    assert len(captured_age_hours) == 1
    assert captured_age_hours[0] is not None
    assert 4.9 < captured_age_hours[0] < 5.1


def test_scan_leaves_age_hours_none_when_post_has_no_timestamp(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "_prune_dead_links", lambda conn, headless: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t", posted_at=None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: [post])

    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t")
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    monkeypatch.setattr(cli, "matches_search", lambda *a, **k: True)

    captured_age_hours = []
    monkeypatch.setattr(
        cli.scoring,
        "score",
        lambda listing_arg, profile, zone_cfg, age_hours=None: captured_age_hours.append(
            age_hours
        )
        or 50,
    )

    cli._scan(make_config(), _Args())

    assert captured_age_hours == [None]
