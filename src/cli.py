from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from rich.console import Console
from rich.panel import Panel

from . import (
    geocode,
    listing_filters,
    llm_extractor,
    scan_state,
    scoring,
    sheets,
    store,
    telegram_notifier,
    zones,
)
from .browser import login_and_save_session, open_scan_session
from .config import Config, load_config
from .listing_models import Listing
from .listing_parser import is_offer_listing, looks_like_explicit_apartment_seeker, parse_listing
from .scraper import (
    RawPost,
    ScanAlreadyRunning,
    ScraperBlocked,
    jitter_between_groups,
    run_lock,
    scrape_group,
)

console = Console()

_SOFT_BLOCK_EMPTY_GROUP_THRESHOLD = 2  # groups returning 0 posts before treating it as a block
_DEAD_LINK_CHECK_LIMIT = 20  # cap per run — never re-check the whole history
_DEAD_LINK_PRUNE_INTERVAL = timedelta(days=1)  # throttled — see _dead_link_prune_due
_DEAD_LINK_MARKERS = (
    "content isn't available",
    "this content isn't available right now",
    "אין אפשרות להציג את התוכן הזה",
)


def cmd_login(_args) -> None:
    login_and_save_session()


def _extract_listing(post: RawPost, group_name: str, config: Config) -> Listing | None:
    """LLM extraction first (when configured), falling back to the regex
    parser when the LLM is unavailable this run — never when it confidently
    classified the post as not an offer, which is a real verdict, not a
    fallback signal."""
    if config.llm.active:
        if looks_like_explicit_apartment_seeker(post.text):
            # A narrow, high-precision "not an offer" signal, checked
            # before spending a paced/budgeted Gemini call — see
            # looks_like_explicit_apartment_seeker's docstring for why
            # it's safe to skip the LLM here specifically (it never
            # matches ambiguous phrasing like "looking for a roommate").
            return None
        try:
            return llm_extractor.extract(
                post.text,
                post.post_url,
                group_name,
                config.llm,
                known_neighborhoods=config.all_neighborhoods,
                images=post.images,
            )
        except llm_extractor.LLMUnavailable as exc:
            # Only reachable when config.llm.active was already True, so
            # this never fires just because the feature is unconfigured —
            # only for a genuine budget-exhaustion or call-failure
            # fallback, worth seeing rather than silently degrading.
            console.print(f"[yellow]LLM extraction unavailable ({exc}) — using regex fallback[/]")

    if not is_offer_listing(post.text):
        return None
    return parse_listing(
        post.text, post.post_url, group_name, config.all_neighborhoods, images=post.images
    )


def _geocode_listing(listing: Listing, config: Config) -> None:
    address = listing.address or (
        listing.neighborhoods_mentioned[0] if listing.neighborhoods_mentioned else None
    )
    if not address:
        return
    coords = geocode.geocode(address)
    if coords is None:
        return
    listing.lat, listing.lon = coords
    listing.distance_m = zones.distance_to_target(listing.lat, listing.lon, config.zone)


def cmd_scan(args) -> None:
    config = load_config()
    try:
        with run_lock():
            blocked = _scan(config, args)
    except ScanAlreadyRunning as exc:
        console.print(f"[red]{exc}[/]")
        sys.exit(1)
    except Exception as exc:
        # A genuinely uncaught exception never reaches either of _scan()'s
        # own heartbeat calls (it propagates straight out), so it gets its
        # own — additive visibility, not error handling, hence the raise.
        _send_heartbeat(config, args, f"🔴 Scan crashed: {exc}")
        raise
    if blocked:
        # Exit code 2 = "blocked/session expired", distinct from a crash
        # (any other non-zero code) or success (0) — lets a cron log show
        # at a glance whether re-running python -m src.cli login is needed.
        sys.exit(2)


def _send_heartbeat(config: Config, args, message: str) -> None:
    """Best-effort Telegram ping at the end of every scan — success,
    blocked, or crashed — so an unattended cron run's outcome is visible
    on the channel you're already watching instead of only in
    data/scan.log. Skipped for --dry-run (a manual/testing invocation,
    same spirit as dry-run already skipping DB writes and match alerts)."""
    if args.dry_run or not config.telegram:
        return
    telegram_notifier.send_text(config.telegram.bot_token, config.telegram.chat_id, message)


def _compute_cutoff(config: Config) -> datetime:
    """The first scan ever run looks back initial_lookback_days; every scan
    after that looks back to the last successful scan instead (self-healing
    if a run was missed), capped so a long outage never scans further back
    than initial_lookback_days.

    Also capped at `now`: on an unattended device (a Termux/Android tablet
    where clock drift/NTP resync after a reboot is plausible), a
    last_scan_completed_at recorded under a clock that was briefly ahead
    of correct time could otherwise sit in the future relative to the
    current (corrected) `now` — every real post would then look "older
    than cutoff" and the scan would skip everything with no error
    surfaced."""
    now = datetime.now(timezone.utc)
    floor = now - timedelta(days=config.scan_window.initial_lookback_days)
    last = scan_state.load_last_scan_completed_at()
    if last is None:
        return floor
    return min(max(last, floor), now)


def _dead_link_prune_due() -> bool:
    """Dead-link pruning revisits up to _DEAD_LINK_CHECK_LIMIT permalinks
    sequentially in the same authenticated session — real added traffic
    and wall-clock cost on every run it happens. Listings rarely go dead
    within hours of matching, so once a day is plenty; no reason to pay
    that cost on every twice-daily scan."""
    last = scan_state.load_last_dead_link_prune_at()
    return last is None or datetime.now(timezone.utc) - last >= _DEAD_LINK_PRUNE_INTERVAL


def _prune_dead_links(context, conn) -> None:
    """Best-effort: revisit a capped batch of the most-recently-matched
    listings and mark any Facebook now shows a "content isn't available"
    placeholder for as dead, so a rented-out apartment stops cluttering
    matches/dashboard instead of sitting there indefinitely. Uses the
    scan's already-open shared context (see browser.open_scan_session)
    rather than its own browser session. Any failure here (network
    hiccup, selector churn) is swallowed — this is a nice-to-have, never
    worth failing or blocking the scan over."""
    urls = store.recent_matched_http_urls(conn, _DEAD_LINK_CHECK_LIMIT)
    if not urls:
        return
    try:
        page = context.new_page()
        try:
            for url in urls:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(random.uniform(1.0, 2.5))
                    body_text = page.locator("body").inner_text(timeout=2000).lower()
                except Exception:
                    continue
                if any(marker in body_text for marker in _DEAD_LINK_MARKERS):
                    store.mark_listing_dead(conn, url)
                    console.print(f"[yellow]Pruned dead listing:[/] {url}")
        finally:
            page.close()
    except Exception:
        pass


def _scan(config: Config, args) -> bool:
    """Returns True if a group scrape hit a checkpoint/login wall
    (ScraperBlocked) — cmd_scan uses this to exit(2) so an unattended cron
    run's log shows "blocked, needs a human" instead of looking like a
    silent hang or an ordinary crash."""
    cutoff = _compute_cutoff(config)
    groups = list(config.facebook_groups)
    random.shuffle(groups)  # don't scan in the same fixed order every run
    new_match_count = 0
    empty_group_count = 0
    with store.connect() as conn, open_scan_session(headless=not args.headed) as context:
        if not args.dry_run and _dead_link_prune_due():
            _prune_dead_links(context, conn)
            scan_state.record_dead_link_prune_completed()
        for i, group in enumerate(groups):
            if i > 0:
                jitter_between_groups()
            console.rule(f"Scanning {group.name}")
            try:
                posts, saw_any_article = scrape_group(
                    context, group, limit=config.posts_per_group, cutoff=cutoff
                )
            except ScraperBlocked as exc:
                console.print(f"[red]Blocked by Facebook:[/] {exc}")
                console.print("[red]Stopping this scan — check your session/login.[/]")
                _send_heartbeat(
                    config,
                    args,
                    f"🔴 Scan blocked by Facebook ({group.name}) — "
                    "session likely expired, re-login needed.",
                )
                return True
            except Exception as exc:
                console.print(
                    f"[red]Unexpected error scanning {group.name}, skipping this group:[/] {exc}"
                )
                continue
            console.print(f"Fetched {len(posts)} posts")

            if not saw_any_article:
                # The page loaded fine (no checkpoint/login wall — that's
                # ScraperBlocked's job above) but rendered zero posts at
                # all, not just zero new-since-cutoff ones. A single
                # occurrence is plausibly just a markup hiccup or a truly
                # dead-quiet group; 2+ in the same run is what a Facebook
                # soft-block (a working-looking but content-stripped page,
                # with no login wall to trip _blocked_reason()) can look
                # like, so that's the bar for treating it as a likely
                # block rather than noise.
                empty_group_count += 1
                if empty_group_count >= _SOFT_BLOCK_EMPTY_GROUP_THRESHOLD:
                    console.print(
                        f"[red]{empty_group_count} groups returned zero posts despite loading "
                        "normally — stopping this scan, possible soft-block.[/]"
                    )
                    _send_heartbeat(
                        config,
                        args,
                        f"🔴 Scan stopped — {empty_group_count} groups returned zero posts "
                        "despite loading normally (possible soft-block or a markup change). "
                        "Check your session.",
                    )
                    return True

            for post in posts:
                if store.listing_seen(conn, post.post_url):
                    continue

                listing = _extract_listing(post, group.name, config)
                if listing is None:
                    continue

                content_hash = store.content_hash_key(listing)
                dup_url = store.find_by_content_hash(conn, content_hash)
                if dup_url and dup_url != listing.post_url:
                    continue  # likely the same flat, already stored under a different key

                phone_hash = store.phone_hash_key(listing)
                dup_phone_url = store.find_by_phone_hash(conn, phone_hash)
                if dup_phone_url and dup_phone_url != listing.post_url:
                    continue  # same phone+price+rooms — likely a reworded repost

                # Cheap filters first (price/rooms/excluded-keywords/broker/
                # etc.), before geocoding — a listing that was always going
                # to fail one of these never pays for a rate-limited lookup.
                candidate_profiles = [
                    p
                    for p in config.searches
                    if listing_filters.matches_without_location(listing, p, config.stay)
                ]
                if not candidate_profiles:
                    continue

                _geocode_listing(listing, config)

                age_hours = (
                    (datetime.now(timezone.utc) - post.posted_at).total_seconds() / 3600
                    if post.posted_at
                    else None
                )

                # A listing can match more than one profile (e.g. it could
                # satisfy both "single room" and "two rooms" if your
                # profiles' ranges overlap), each scored on that profile's
                # own criteria (different price ranges score differently).
                matched_profiles = [
                    p
                    for p in candidate_profiles
                    if listing_filters.location_ok(listing, p, config.zone)
                ]
                scores = {
                    p.name: scoring.score(listing, p, config.zone, age_hours)
                    for p in matched_profiles
                }
                if matched_profiles:
                    listing.score = max(scores.values())

                if args.dry_run:
                    for p in matched_profiles:
                        console.print(
                            f"[green]Would match[/] [{p.emoji} {p.name}] ({group.name}): "
                            f"{listing.price or '?'} ILS, {listing.rooms or '?'} rooms — "
                            f"{listing.post_url}"
                        )
                    continue

                listing_id = store.insert_listing(
                    conn,
                    listing,
                    matched_profiles=[p.name for p in matched_profiles],
                    content_hash=content_hash,
                    phone_hash=phone_hash,
                )
                if not listing_id:
                    continue  # INSERT OR IGNORE hit a duplicate race
                if not matched_profiles:
                    continue
                new_match_count += 1

                for p in matched_profiles:
                    console.print(
                        f"[green]Match![/] [{p.emoji} {p.name}] ({group.name}): "
                        f"{listing.price or '?'} ILS, {listing.rooms or '?'} rooms, "
                        f"score {scores[p.name]} — {listing.post_url}"
                    )
                sheets.save_listing(listing)
                if config.telegram:
                    any_sent = False
                    for p in matched_profiles:
                        sent = telegram_notifier.send_listing(
                            config.telegram.bot_token,
                            config.telegram.chat_id,
                            listing,
                            p,
                            scores[p.name],
                            conn=conn,
                        )
                        any_sent = any_sent or sent
                        if not sent:
                            console.print(f"[red]Telegram notify failed for {p.name}[/]")
                    if any_sent:
                        store.mark_listing_notified(conn, listing_id)

            # Shrinks the write-lock window from "the whole scan" to
            # roughly one group's worth of posts, giving bot_listener.py's
            # concurrent vote-button writes frequent gaps to get in rather
            # than waiting out one long-lived multi-minute transaction.
            conn.commit()

    # Only reached if every group's scrape_group() completed cleanly (no
    # ScraperBlocked) — the early `return True` above skips this, so a
    # blocked run doesn't advance the watermark and the next run safely
    # re-covers that time range (cheap: dedup already makes it a no-op for
    # anything already stored).
    sheets.flush()  # one re-sort for the whole scan, not one per listing
    scan_state.record_scan_completed()
    word = "match" if new_match_count == 1 else "matches"
    _send_heartbeat(config, args, f"✅ Scan complete — {new_match_count} new {word}.")
    console.print("\nRun `python scripts/matches.py` to see everything found so far.")
    return False


def cmd_matches(_args) -> None:
    """List apartments found that matched your search criteria, best score first."""
    with store.connect() as conn:
        listings = store.list_listings(conn, matched_only=True)
        if not listings:
            console.print("No matching apartments found yet.")
            return
        scores = store.effective_scores(conn, listings)
        listings.sort(key=lambda row: scores[row.post_url], reverse=True)
        for listing in listings:
            score = scores[listing.post_url]
            profiles = ", ".join(listing.profile_names()) or "?"
            price = f"{listing.price} ILS" if listing.price is not None else "Price not listed"
            body_lines = [
                f"[bold]{price}[/] · "
                f"{listing.rooms or '?'} rooms · score {score} · matched: {profiles}",
                listing.address or listing.neighborhoods or "area unknown",
            ]
            if listing.lease_start_date or listing.lease_duration_days:
                stay = " · ".join(
                    part
                    for part in [
                        listing.lease_start_date and f"from {listing.lease_start_date}",
                        listing.lease_duration_days and f"{listing.lease_duration_days} days",
                    ]
                    if part
                )
                body_lines.append(stay)
            if listing.phone:
                body_lines.append(listing.phone)
            body_lines.append(listing.post_url)
            body_lines.append("")
            body_lines.append(listing.summary or listing.raw_text)
            console.print(
                Panel(
                    "\n".join(body_lines),
                    title=f"Listing #{listing.id}" + (" (notified)" if listing.notified else ""),
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="TLV apartment search agent")
    sub = parser.add_subparsers(dest="command", required=True)

    login_parser = sub.add_parser("login", help="Log into Facebook and save the session")
    login_parser.set_defaults(func=cmd_login)

    scan_parser = sub.add_parser("scan", help="Scan configured groups for matching apartments")
    scan_parser.add_argument(
        "--headed", action="store_true", help="Show the browser window while scanning"
    )
    scan_parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Classify and print what would match, without writing to the DB or notifying",
    )
    scan_parser.set_defaults(func=cmd_scan)

    sub.add_parser(
        "matches", help="List apartments found matching your search criteria"
    ).set_defaults(func=cmd_matches)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
