from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel

from . import geocode, llm_extractor, scoring, sheets, store, telegram_notifier, zones
from .browser import login_and_save_session
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
            _scan(config, args)
    except ScanAlreadyRunning as exc:
        console.print(f"[red]{exc}[/]")
        sys.exit(1)


def _scan(config: Config, args) -> None:
    with store.connect() as conn:
        for i, group in enumerate(config.facebook_groups):
            if i > 0:
                jitter_between_groups()
            console.rule(f"Scanning {group.name}")
            try:
                posts = scrape_group(group, limit=config.posts_per_group, headless=not args.headed)
            except ScraperBlocked as exc:
                console.print(f"[red]Blocked by Facebook:[/] {exc}")
                console.print("[red]Stopping this scan — check your session/login.[/]")
                return
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

    console.print("\nRun `python scripts/matches.py` to see everything found so far.")


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
            body_lines = [
                f"[bold]{listing.price or '?'} ILS[/] · "
                f"{listing.rooms or '?'} rooms · score {score} · matched: {profiles}",
                listing.address or listing.neighborhoods or "area unknown",
            ]
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
