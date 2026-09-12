from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel

from . import store
from .browser import login_and_save_session
from .config import load_config
from .listing_filters import matches as matches_search
from .listing_parser import is_offer_listing, parse_listing
from .scraper import scrape_group
from .telegram_notifier import send_listing

console = Console()


def cmd_login(_args) -> None:
    login_and_save_session()


def cmd_scan(args) -> None:
    config = load_config()
    with store.connect() as conn:
        for group in config.facebook_groups:
            console.rule(f"Scanning {group.name}")
            posts = scrape_group(group, limit=config.posts_per_group, headless=not args.headed)
            console.print(f"Fetched {len(posts)} posts")

            for post in posts:
                if store.listing_seen(conn, post.post_url):
                    continue
                if not is_offer_listing(post.text):
                    continue

                listing = parse_listing(
                    post.text, post.post_url, group.name, config.search.neighborhoods
                )
                matched = matches_search(listing, config.search)
                listing_id = store.insert_listing(conn, listing, matched=matched)
                if not listing_id:
                    continue  # INSERT OR IGNORE hit a duplicate race
                if not matched:
                    continue

                console.print(
                    f"[green]Match![/] ({group.name}): "
                    f"{listing.price or '?'} ILS, {listing.rooms or '?'} rooms — "
                    f"{listing.post_url}"
                )
                if config.telegram:
                    try:
                        send_listing(config.telegram.bot_token, config.telegram.chat_id, listing)
                        store.mark_listing_notified(conn, listing_id)
                    except Exception as e:
                        console.print(f"[red]Telegram notify failed:[/] {e}")

    console.print("\nRun `python scripts/matches.py` to see everything found so far.")


def cmd_matches(_args) -> None:
    """List apartments found that matched your search criteria."""
    with store.connect() as conn:
        listings = store.list_listings(conn, matched_only=True)
        if not listings:
            console.print("No matching apartments found yet.")
            return
        for listing in listings:
            console.print(
                Panel(
                    f"[bold]{listing.price or '?'} ILS[/] · "
                    f"{listing.rooms or '?'} rooms · "
                    f"{listing.neighborhoods or 'area unknown'}\n"
                    f"{listing.post_url}\n\n{listing.raw_text}",
                    title=f"Listing #{listing.id}"
                    + (" (notified)" if listing.notified else ""),
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="TLV apartment search agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Log into Facebook and save the session").set_defaults(func=cmd_login)

    scan_parser = sub.add_parser("scan", help="Scan configured groups for matching apartments")
    scan_parser.add_argument(
        "--headed", action="store_true", help="Show the browser window while scanning"
    )
    scan_parser.set_defaults(func=cmd_scan)

    sub.add_parser(
        "matches", help="List apartments found matching your search criteria"
    ).set_defaults(func=cmd_matches)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
