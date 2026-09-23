from __future__ import annotations

import argparse
import random
import sys
import time
from datetime import datetime, timedelta, timezone

from playwright.sync_api import sync_playwright
from rich.console import Console
from rich.panel import Panel

from . import geocode, llm_extractor, scan_state, scoring, sheets, store, telegram_notifier, zones
from .browser import login_and_save_session, open_authenticated_context
from .config import Config, load_config
from .listing_filters import matches as matches_search
from .listing_models import Listing
from .listing_parser import is_offer_listing, parse_listing
from .scraper import (
    RawPost,
    ScanAlreadyRunning,
    ScraperBlocked,
    jitter_between_groups,
    run_lock,
    scrape_group,
)

console = Console()

_DEAD_LINK_CHECK_LIMIT = 20  # cap per run — never re-check the whole history
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
        try:
            return llm_extractor.extract(
                post.text,
                post.post_url,
                group_name,
                config.llm,
                known_neighborhoods=config.all_neighborhoods,
                images=post.images,
            )
        except llm_extractor.LLMUnavailable:
            pass  # fall through to the regex parser below

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
    if blocked:
        # Exit code 2 = "blocked/session expired", distinct from a crash
        # (any other non-zero code) or success (0) — lets a cron log show
        # at a glance whether re-running python -m src.cli login is needed.
        sys.exit(2)


def _compute_cutoff(config: Config) -> datetime:
    """The first scan ever run looks back initial_lookback_days; every scan
    after that looks back to the last successful scan instead (self-healing
    if a run was missed), capped so a long outage never scans further back
    than initial_lookback_days."""
    now = datetime.now(timezone.utc)
    floor = now - timedelta(days=config.scan_window.initial_lookback_days)
    last = scan_state.load_last_scan_completed_at()
    if last is None:
        return floor
    return max(last, floor)


def _prune_dead_links(conn, headless: bool) -> None:
    """Best-effort: revisit a capped batch of the most-recently-matched
    listings and mark any Facebook now shows a "content isn't available"
    placeholder for as dead, so a rented-out apartment stops cluttering
    matches/dashboard instead of sitting there indefinitely. Any failure
    here (network hiccup, selector churn) is swallowed — this is a
    nice-to-have, never worth failing or blocking the scan over."""
    rows = store.list_listings(conn, matched_only=True)
    rows.sort(key=lambda r: r.created_at, reverse=True)
    candidates = [r for r in rows if r.post_url.startswith("http")][:_DEAD_LINK_CHECK_LIMIT]
    if not candidates:
        return
    try:
        with sync_playwright() as p:
            context = open_authenticated_context(p, headless=headless)
            page = context.new_page()
            for row in candidates:
                try:
                    page.goto(row.post_url, wait_until="domcontentloaded", timeout=15000)
                    time.sleep(random.uniform(1.0, 2.5))
                    body_text = page.locator("body").inner_text(timeout=2000).lower()
                except Exception:
                    continue
                if any(marker in body_text for marker in _DEAD_LINK_MARKERS):
                    store.mark_listing_dead(conn, row.post_url)
                    console.print(f"[yellow]Pruned dead listing:[/] {row.post_url}")
            context.close()
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
    with store.connect() as conn:
        if not args.dry_run:
            _prune_dead_links(conn, headless=not args.headed)
        for i, group in enumerate(groups):
            if i > 0:
                jitter_between_groups()
            console.rule(f"Scanning {group.name}")
            try:
                posts = scrape_group(
                    group, limit=config.posts_per_group, cutoff=cutoff, headless=not args.headed
                )
            except ScraperBlocked as exc:
                console.print(f"[red]Blocked by Facebook:[/] {exc}")
                console.print("[red]Stopping this scan — check your session/login.[/]")
                return True
            console.print(f"Fetched {len(posts)} posts")

            for post in posts:
                if store.listing_seen(conn, post.post_url):
                    continue

                listing = _extract_listing(post, group.name, config)
                if listing is None:
                    continue

                dup_url = store.find_by_content_hash(conn, store.content_hash_key(listing))
                if dup_url and dup_url != listing.post_url:
                    continue  # likely the same flat, already stored under a different key

                dup_phone_url = store.find_by_phone_hash(conn, store.phone_hash_key(listing))
                if dup_phone_url and dup_phone_url != listing.post_url:
                    continue  # same phone+price+rooms — likely a reworded repost

                _geocode_listing(listing, config)

                # Evaluate this one extraction against every configured
                # profile — a listing can match more than one (e.g. it
                # could satisfy both "single room" and "two rooms" if your
                # profiles' ranges overlap), each scored on that profile's
                # own criteria (different price ranges score differently).
                matched_profiles = [
                    p
                    for p in config.searches
                    if matches_search(listing, p, config.zone, config.stay)
                ]
                scores = {p.name: scoring.score(listing, p, config.zone) for p in matched_profiles}
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
                    conn, listing, matched_profiles=[p.name for p in matched_profiles]
                )
                if not listing_id:
                    continue  # INSERT OR IGNORE hit a duplicate race
                if not matched_profiles:
                    continue

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

    # Only reached if every group's scrape_group() completed cleanly (no
    # ScraperBlocked) — the early `return True` above skips this, so a
    # blocked run doesn't advance the watermark and the next run safely
    # re-covers that time range (cheap: dedup already makes it a no-op for
    # anything already stored).
    scan_state.record_scan_completed()
    console.print("\nRun `python scripts/matches.py` to see everything found so far.")
    return False


def cmd_matches(_args) -> None:
    """List apartments found that matched your search criteria, best score first."""
    with store.connect() as conn:
        listings = store.list_listings(conn, matched_only=True)
        if not listings:
            console.print("No matching apartments found yet.")
            return
        listings.sort(key=lambda row: store.effective_score(conn, row), reverse=True)
        for listing in listings:
            score = store.effective_score(conn, listing)
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
