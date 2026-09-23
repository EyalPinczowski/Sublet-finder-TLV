from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

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


@contextmanager
def _fake_scan_session(headless=True):
    """Stands in for cli.open_scan_session in tests — no real Playwright
    session, no storage_state.json required."""
    yield MagicMock()


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
    def __init__(self, headed=False, dry_run=False, explain=False):
        self.headed = headed
        self.dry_run = dry_run
        self.explain = explain


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


def test_compute_cutoff_never_exceeds_now_under_clock_skew(monkeypatch):
    """A last_scan_completed_at recorded under a briefly-ahead clock (e.g.
    an unattended tablet's clock drifting before an NTP resync) must not
    produce a cutoff in the future — that would make every real post look
    "older than cutoff" and silently skip the whole scan."""
    future = datetime.now(timezone.utc) + timedelta(hours=6)
    monkeypatch.setattr(scan_state, "load_last_scan_completed_at", lambda: future)
    config = make_config(scan_window=ScanWindowConfig(initial_lookback_days=4))
    cutoff = cli._compute_cutoff(config)
    assert cutoff <= datetime.now(timezone.utc)


# --- _scan: scan-state write only on a clean, unblocked completion ---


def test_scan_records_completion_when_all_groups_succeed(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([], True))
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
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli.random, "shuffle", lambda seq: None)  # deterministic order

    def fake_scrape(context, group, **kwargs):
        if group.name == "g1":
            return [], True
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


def test_scan_aborts_after_two_groups_render_zero_articles(isolated_db, monkeypatch):
    """A Facebook soft-block can serve a working-looking page with no
    login wall but zero rendered posts — distinct from a group that just
    has nothing new since the cutoff (saw_any_article=True, posts=[])."""
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli.random, "shuffle", lambda seq: None)
    reached = []

    def fake_scrape(context, group, **kwargs):
        reached.append(group.name)
        return [], False  # every group renders nothing at all

    monkeypatch.setattr(cli, "scrape_group", fake_scrape)
    recorded = []
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: recorded.append(True))
    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a[2]))
    config = make_config(
        telegram=_telegram_config(),
        facebook_groups=[
            FacebookGroup(name="g1", url="https://facebook.com/groups/1"),
            FacebookGroup(name="g2", url="https://facebook.com/groups/2"),
            FacebookGroup(name="g3", url="https://facebook.com/groups/3"),
        ],
    )
    blocked = cli._scan(config, _Args())
    assert blocked is True
    assert reached == ["g1", "g2"]  # stopped after the 2nd empty group, never reached g3
    assert recorded == []
    assert len(sent) == 1
    assert "soft-block" in sent[0].lower() or "zero posts" in sent[0].lower()


def test_scan_does_not_abort_on_a_single_empty_group(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli.random, "shuffle", lambda seq: None)
    reached = []

    def fake_scrape(context, group, **kwargs):
        reached.append(group.name)
        return ([], False) if group.name == "g1" else ([], True)

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
    assert blocked is False
    assert reached == ["g1", "g2"]  # both groups scanned normally
    assert recorded == [True]


def test_scan_does_not_count_a_normal_empty_result_toward_soft_block(isolated_db, monkeypatch):
    """saw_any_article=True with zero posts (nothing new since the cutoff)
    is normal, healthy operation — it must never contribute toward the
    soft-block escalation counter."""
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([], True))
    recorded = []
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: recorded.append(True))
    config = make_config(
        facebook_groups=[
            FacebookGroup(name="g1", url="https://facebook.com/groups/1"),
            FacebookGroup(name="g2", url="https://facebook.com/groups/2"),
            FacebookGroup(name="g3", url="https://facebook.com/groups/3"),
        ]
    )
    blocked = cli._scan(config, _Args())
    assert blocked is False
    assert recorded == [True]


def test_scan_continues_to_next_group_on_a_generic_exception(isolated_db, monkeypatch):
    """Unlike ScraperBlocked (which stops the whole scan), any other
    exception from one group should only skip that group."""
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli.random, "shuffle", lambda seq: None)
    reached = []

    def fake_scrape(context, group, **kwargs):
        if group.name == "g1":
            raise RuntimeError("Playwright hiccup")
        reached.append(group.name)
        return [], True

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
    assert blocked is False
    assert reached == ["g2"]  # g1 failed and was skipped, g2 still ran
    assert recorded == [True]  # a skipped group isn't a block — still records


def test_scan_passes_computed_cutoff_to_scrape_group(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    expected_cutoff = datetime.now(timezone.utc) - timedelta(hours=12)
    monkeypatch.setattr(cli, "_compute_cutoff", lambda config: expected_cutoff)
    seen_cutoffs = []

    def fake_scrape(context, group, limit, cutoff):
        seen_cutoffs.append(cutoff)
        return [], True

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
        assert cli._prune_dead_links(MagicMock(), conn) is True  # nothing to do isn't a failure


def test_prune_dead_links_returns_false_when_the_page_cant_even_open(isolated_db):
    listing = Listing(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="g1",
        raw_text="t",
        score=80,
    )
    context = MagicMock()
    context.new_page.side_effect = Exception("browser context is dead")
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        assert cli._prune_dead_links(context, conn) is False


def test_prune_dead_links_returns_true_despite_a_single_url_failing(isolated_db):
    """A per-URL failure (network hiccup, selector churn) is still
    best-effort and swallowed — the pass as a whole still "completed"."""
    listing = Listing(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="g1",
        raw_text="t",
        score=80,
    )
    context = MagicMock()
    context.new_page.return_value.goto.side_effect = Exception("timed out")
    with store.connect() as conn:
        store.insert_listing(conn, listing, matched_profiles=["default"])
        assert cli._prune_dead_links(context, conn) is True
        context.new_page.return_value.close.assert_called_once()


# --- dead-link pruning: throttled to roughly once a day ---


def test_dead_link_prune_due_when_never_pruned_before(isolated_db):
    assert cli._dead_link_prune_due() is True


def test_dead_link_prune_not_due_right_after_pruning(isolated_db):
    scan_state.record_dead_link_prune_completed()
    assert cli._dead_link_prune_due() is False


def test_dead_link_prune_due_again_after_the_interval_passes(isolated_db):
    scan_state.record_dead_link_prune_completed(
        datetime.now(timezone.utc) - timedelta(days=2)
    )
    assert cli._dead_link_prune_due() is True


def test_scan_skips_pruning_when_not_due(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([], True))
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    scan_state.record_dead_link_prune_completed()  # just pruned — not due again

    prune_calls = []
    monkeypatch.setattr(
        cli, "_prune_dead_links", lambda context, conn: prune_calls.append(1)
    )
    cli._scan(make_config(), _Args())
    assert prune_calls == []


def test_scan_prunes_and_records_when_due(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([], True))
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    prune_calls = []

    def fake_prune(context, conn):
        prune_calls.append(1)
        return True

    monkeypatch.setattr(cli, "_prune_dead_links", fake_prune)
    cli._scan(make_config(), _Args())
    assert prune_calls == [1]
    assert scan_state.load_last_dead_link_prune_at() is not None


def test_scan_does_not_record_prune_completion_on_total_failure(isolated_db, monkeypatch):
    """A total pruning failure (e.g. the browser context couldn't open a
    page) must not advance the once-a-day throttle — that would silently
    disable retries for up to 24h even though nothing was actually
    checked."""
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([], True))
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: False)

    cli._scan(make_config(), _Args())
    assert scan_state.load_last_dead_link_prune_at() is None


def test_scan_never_prunes_on_dry_run_even_when_due(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([], True))
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    prune_calls = []
    monkeypatch.setattr(
        cli, "_prune_dead_links", lambda context, conn: prune_calls.append(1)
    )
    cli._scan(make_config(), _Args(dry_run=True))
    assert prune_calls == []


# --- _extract_listing: narrow LLM pre-filter skips explicit seeker posts ---


def _llm_config():
    from src.config import LLMConfig

    return LLMConfig(enabled=True, api_key="fake-key")


def test_extract_listing_skips_llm_call_for_explicit_seeker_post(monkeypatch):
    calls = []
    monkeypatch.setattr(cli.llm_extractor, "extract", lambda *a, **k: calls.append(1))
    post = RawPost(post_url="https://fb.com/1", author="a", text="מחפשת דירה בפלורנטין")
    result = cli._extract_listing(post, "g1", make_config(llm=_llm_config()))
    assert result is None
    assert calls == []  # never reached the paced/budgeted Gemini call


def test_extract_listing_still_calls_llm_for_roommate_wanted_post(monkeypatch):
    """"מחפש שותף" ("looking for a roommate") must still go through the LLM
    — it's ambiguous (often an offer), unlike an explicit "looking for an
    apartment" post."""
    listing = Listing(post_url="https://fb.com/1", group_name="g1", raw_text="t")
    monkeypatch.setattr(cli.llm_extractor, "extract", lambda *a, **k: listing)
    post = RawPost(post_url="https://fb.com/1", author="a", text="מחפש שותף לדירה שלי בפלורנטין")
    result = cli._extract_listing(post, "g1", make_config(llm=_llm_config()))
    assert result is listing


def test_extract_listing_calls_llm_for_a_normal_offer_post(monkeypatch):
    listing = Listing(post_url="https://fb.com/1", group_name="g1", raw_text="t")
    monkeypatch.setattr(cli.llm_extractor, "extract", lambda *a, **k: listing)
    post = RawPost(post_url="https://fb.com/1", author="a", text="סאבלט בפלורנטין, 4500 ₪")
    result = cli._extract_listing(post, "g1", make_config(llm=_llm_config()))
    assert result is listing


# --- freshness scoring: post.posted_at must actually reach scoring.score ---


def _patch_matches_everything(monkeypatch):
    monkeypatch.setattr(cli.listing_filters, "matches_without_location", lambda *a, **k: True)
    monkeypatch.setattr(cli.listing_filters, "location_ok", lambda *a, **k: True)


def test_scan_threads_post_age_into_scoring(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    posted_at = datetime.now(timezone.utc) - timedelta(hours=5)
    post = RawPost(post_url="https://fb.com/1", author="a", text="t", posted_at=posted_at)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))

    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t")
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    _patch_matches_everything(monkeypatch)

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
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t", posted_at=None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))

    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t")
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    _patch_matches_everything(monkeypatch)

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


# --- deferred geocoding: a listing failing the cheap check is never geocoded ---


def test_scan_skips_geocoding_when_cheap_filters_already_fail(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t")
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    monkeypatch.setattr(cli.listing_filters, "matches_without_location", lambda *a, **k: False)

    geocode_calls = []
    monkeypatch.setattr(cli, "_geocode_listing", lambda listing, config: geocode_calls.append(1))

    cli._scan(make_config(), _Args())
    assert geocode_calls == []


def test_scan_geocodes_when_cheap_filters_pass(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t")
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    _patch_matches_everything(monkeypatch)

    geocode_calls = []
    monkeypatch.setattr(cli, "_geocode_listing", lambda listing, config: geocode_calls.append(1))

    cli._scan(make_config(), _Args())
    assert geocode_calls == [1]


# --- --explain: sanity-check diagnostics for listings that match nothing ---


def test_explain_implies_dry_run(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    _patch_matches_everything(monkeypatch)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t", price=4500)
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)

    args = _Args(explain=True)
    cli._scan(make_config(), args)
    assert args.dry_run is True

    with store.connect() as conn:
        assert store.list_listings(conn, matched_only=True) == []


def test_explain_prints_reasons_when_no_profile_matches_without_location(
    isolated_db, monkeypatch, capsys
):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t", price=9000)
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    monkeypatch.setattr(cli.listing_filters, "matches_without_location", lambda *a, **k: False)

    geocode_calls = []
    monkeypatch.setattr(cli, "_geocode_listing", lambda listing, config: geocode_calls.append(1))

    config = make_config(searches=[SearchConfig(name="default", price_max=5000)])
    cli._scan(config, _Args(explain=True))

    assert geocode_calls == []  # still never geocodes a listing failing the cheap phase
    out = capsys.readouterr().out
    assert "No match" in out
    assert "default" in out
    assert "above max" in out
    assert post.post_url in out


def test_explain_prints_reasons_when_only_location_fails(isolated_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(
        post_url=post.post_url, group_name="g1", raw_text="t", price=4500,
        neighborhoods_mentioned=[],
    )
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    monkeypatch.setattr(cli.listing_filters, "matches_without_location", lambda *a, **k: True)
    monkeypatch.setattr(cli.listing_filters, "location_ok", lambda *a, **k: False)
    monkeypatch.setattr(cli, "_geocode_listing", lambda listing, config: None)

    config = make_config(
        searches=[SearchConfig(name="default", neighborhoods=["florentin"])]
    )
    cli._scan(config, _Args(explain=True))

    out = capsys.readouterr().out
    assert "No match" in out
    assert "neighborhood" in out


def test_no_explain_output_without_the_flag(isolated_db, monkeypatch, capsys):
    """--dry-run alone (no --explain) must not gain the diagnostic
    printing — only an explicit --explain opts into it."""
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t", price=9000)
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    monkeypatch.setattr(cli.listing_filters, "matches_without_location", lambda *a, **k: False)

    config = make_config(searches=[SearchConfig(name="default", price_max=5000)])
    cli._scan(config, _Args(dry_run=True))

    out = capsys.readouterr().out
    assert "No match" not in out


# --- console output: a missing price is labeled "potential" ---


def test_dry_run_labels_a_missing_price_as_potential(isolated_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    _patch_matches_everything(monkeypatch)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t", price=None)
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)

    cli._scan(make_config(), _Args(dry_run=True))
    out = capsys.readouterr().out
    assert "(potential — price unknown)" in out


def test_dry_run_does_not_label_a_known_price_as_potential(isolated_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    _patch_matches_everything(monkeypatch)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t", price=3300)
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)

    cli._scan(make_config(), _Args(dry_run=True))
    out = capsys.readouterr().out
    assert "(potential — price unknown)" not in out


def test_real_match_labels_a_missing_price_as_potential(isolated_db, monkeypatch, capsys):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    _patch_matches_everything(monkeypatch)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t", price=None)
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)

    cli._scan(make_config(), _Args())
    out = capsys.readouterr().out
    assert "(potential — price unknown)" in out


# --- cross-group dedup: the same apartment posted to 2 groups in one scan ---


def test_scan_does_not_suggest_the_same_apartment_twice_across_groups(isolated_db, monkeypatch):
    """The exact scenario a real repost looks like: someone posts the same
    apartment to two different groups, worded slightly differently each
    time ("רחוב דיזנגוף 120" vs "דיזנגוף 120, תל אביב") — content_hash_key's
    normalization must still recognize them as the same listing, so it's
    matched/notified once, not once per group."""
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(cli.random, "shuffle", lambda seq: None)  # deterministic order
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    _patch_matches_everything(monkeypatch)

    post_a = RawPost(post_url="https://fb.com/groups/1/posts/1", author="a", text="t")
    post_b = RawPost(post_url="https://fb.com/groups/2/posts/2", author="a", text="t")
    listing_a = Listing(
        post_url=post_a.post_url,
        group_name="g1",
        raw_text="t",
        price=4500,
        rooms=2.0,
        address="רחוב דיזנגוף 120",
    )
    listing_b = Listing(
        post_url=post_b.post_url,
        group_name="g2",
        raw_text="t",
        price=4500,
        rooms=2.0,
        address="דיזנגוף 120, תל אביב",
    )

    def fake_scrape(context, group, **kwargs):
        return ([post_a], True) if group.name == "g1" else ([post_b], True)

    def fake_extract(post, group_name, config):
        return listing_a if post is post_a else listing_b

    monkeypatch.setattr(cli, "scrape_group", fake_scrape)
    monkeypatch.setattr(cli, "_extract_listing", fake_extract)

    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a[2]))

    config = make_config(
        telegram=_telegram_config(),
        facebook_groups=[
            FacebookGroup(name="g1", url="https://facebook.com/groups/1"),
            FacebookGroup(name="g2", url="https://facebook.com/groups/2"),
        ],
    )
    cli._scan(config, _Args())

    with store.connect() as conn:
        listings = store.list_listings(conn, matched_only=True)
    assert len(listings) == 1  # the second post never got its own row
    assert sent == ["✅ Scan complete — 1 new match."]


# --- Telegram heartbeat ---


def _telegram_config():
    from src.config import TelegramConfig

    return TelegramConfig(bot_token="tok", chat_id="chat")


def test_heartbeat_skipped_without_telegram_configured():
    sent = []
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a))
        cli._send_heartbeat(make_config(telegram=None), _Args(dry_run=False), "hello")
    assert sent == []


def test_heartbeat_skipped_on_dry_run(monkeypatch):
    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a))
    cli._send_heartbeat(make_config(telegram=_telegram_config()), _Args(dry_run=True), "hello")
    assert sent == []


def test_heartbeat_sends_when_telegram_configured_and_not_dry_run(monkeypatch):
    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a))
    cli._send_heartbeat(make_config(telegram=_telegram_config()), _Args(dry_run=False), "hello")
    assert sent == [("tok", "chat", "hello")]


def test_scan_sends_success_heartbeat_with_match_count(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)

    post = RawPost(post_url="https://fb.com/1", author="a", text="t")
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([post], True))
    listing = Listing(post_url=post.post_url, group_name="g1", raw_text="t")
    monkeypatch.setattr(cli, "_extract_listing", lambda p, g, c: listing)
    _patch_matches_everything(monkeypatch)

    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a[2]))

    cli._scan(make_config(telegram=_telegram_config()), _Args())
    assert sent == ["✅ Scan complete — 1 new match."]


def test_scan_sends_blocked_heartbeat(isolated_db, monkeypatch):
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)

    def fake_scrape(context, group, **kwargs):
        raise ScraperBlocked("g1: checkpoint")

    monkeypatch.setattr(cli, "scrape_group", fake_scrape)
    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a[2]))

    cli._scan(make_config(telegram=_telegram_config()), _Args())
    assert len(sent) == 1
    assert "blocked" in sent[0].lower()


def test_cmd_scan_sends_crash_heartbeat_and_reraises(isolated_db, monkeypatch, tmp_path):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    monkeypatch.setattr(cli, "load_config", lambda: make_config(telegram=_telegram_config()))

    def fake_scan(config, args):
        raise RuntimeError("boom")

    monkeypatch.setattr(cli, "_scan", fake_scan)
    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a[2]))

    with pytest.raises(RuntimeError, match="boom"):
        cli.cmd_scan(_Args())
    assert len(sent) == 1
    assert "crashed" in sent[0].lower()


class _CommitCountingConn:
    """sqlite3.Connection is a C type with no __dict__ — its methods can't
    be monkeypatched on the instance or the class, so counting commits
    needs a thin delegating proxy instead."""

    def __init__(self, real_conn, counter: list):
        object.__setattr__(self, "_real_conn", real_conn)
        object.__setattr__(self, "_counter", counter)

    def commit(self):
        self._counter.append(1)
        self._real_conn.commit()

    def __getattr__(self, name):
        return getattr(self._real_conn, name)


def test_scan_commits_once_per_group_processed(isolated_db, monkeypatch):
    """Shrinks the write-lock window from the whole scan to roughly one
    group's worth of posts, so bot_listener.py's concurrent writes get
    frequent gaps instead of waiting out one long-lived transaction."""
    monkeypatch.setattr(cli, "open_scan_session", _fake_scan_session)
    monkeypatch.setattr(cli, "_prune_dead_links", lambda context, conn: None)
    monkeypatch.setattr(cli, "jitter_between_groups", lambda: None)
    monkeypatch.setattr(scan_state, "record_scan_completed", lambda: None)
    monkeypatch.setattr(cli, "scrape_group", lambda *a, **k: ([], True))

    commit_calls: list = []
    real_connect = store.connect

    @contextmanager
    def counting_connect():
        with real_connect() as real_conn:
            yield _CommitCountingConn(real_conn, commit_calls)

    monkeypatch.setattr(store, "connect", counting_connect)

    config = make_config(
        facebook_groups=[
            FacebookGroup(name="g1", url="https://facebook.com/groups/1"),
            FacebookGroup(name="g2", url="https://facebook.com/groups/2"),
            FacebookGroup(name="g3", url="https://facebook.com/groups/3"),
        ]
    )
    cli._scan(config, _Args())
    assert len(commit_calls) == 3  # one per group; store.connect()'s own final commit
    # doesn't count here since the proxy's __getattr__ bypasses it, but the real
    # connection is still committed inside `with real_connect() as real_conn:`.


def test_cmd_scan_does_not_send_crash_heartbeat_when_already_running(
    isolated_db, monkeypatch, tmp_path
):
    monkeypatch.setattr(scraper, "LOCK_PATH", tmp_path / "scan.lock")
    monkeypatch.setattr(cli, "load_config", lambda: make_config(telegram=_telegram_config()))
    monkeypatch.setattr(
        cli,
        "_scan",
        lambda config, args: (_ for _ in ()).throw(scraper.ScanAlreadyRunning("already running")),
    )
    sent = []
    monkeypatch.setattr(cli.telegram_notifier, "send_text", lambda *a, **k: sent.append(a[2]))

    with pytest.raises(SystemExit) as exc_info:
        cli.cmd_scan(_Args())
    assert exc_info.value.code == 1
    assert sent == []
