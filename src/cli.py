from __future__ import annotations

import argparse
import sys

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Prompt

from . import store
from .browser import login_and_save_session
from .config import load_config
from .drafter import draft_message
from .scraper import matches_keywords, scrape_group
from .screener import screen_post

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
                if store.post_seen(conn, post.post_url):
                    continue
                if not matches_keywords(post.text, config.search_keywords):
                    continue

                lead_id = store.insert_raw_post(
                    conn, post.post_url, group.name, post.author, post.text
                )
                if lead_id == 0:
                    continue  # INSERT OR IGNORE hit a duplicate race

                result = screen_post(config, post.text)
                store.update_screening(
                    conn, lead_id, result.get("fit_score", 0), result.get("notes", "")
                )

                if not result.get("is_seeking_apartment") or result.get("fit_score", 0) < config.min_fit_score:
                    store.set_status(conn, lead_id, "rejected")
                    continue

                message = draft_message(config, post.text, result.get("notes", ""))
                store.update_draft(conn, lead_id, message)
                console.print(f"[green]New lead[/] (score {result['fit_score']}): {post.author}")

    console.print("\nRun `python -m src.cli review` to go through new leads.")


def cmd_review(_args) -> None:
    config = load_config()
    with store.connect() as conn:
        leads = store.list_leads(conn, status="new", min_fit_score=config.min_fit_score)
        if not leads:
            console.print("No new leads to review.")
            return

        for lead in leads:
            console.print(
                Panel(
                    f"[bold]Group:[/] {lead.group_name}\n"
                    f"[bold]Author:[/] {lead.author}\n"
                    f"[bold]Fit score:[/] {lead.fit_score}\n"
                    f"[bold]Notes:[/] {lead.screening_notes}\n\n"
                    f"[bold]Post:[/]\n{lead.post_text}\n\n"
                    f"[bold cyan]Draft message:[/]\n{lead.draft_message}\n\n"
                    f"[bold]Post URL:[/] {lead.post_url}",
                    title=f"Lead #{lead.id}",
                )
            )
            choice = Prompt.ask(
                "Approve, reject, edit draft, or skip?",
                choices=["a", "r", "e", "s"],
                default="s",
            )
            if choice == "a":
                store.set_status(conn, lead.id, "approved")
                console.print("[green]Approved.[/] Copy the draft above and send it yourself.")
            elif choice == "r":
                store.set_status(conn, lead.id, "rejected")
            elif choice == "e":
                new_text = Prompt.ask("New draft text", default=lead.draft_message)
                store.update_draft(conn, lead.id, new_text)
                store.set_status(conn, lead.id, "approved")
            else:
                continue


def cmd_approved(_args) -> None:
    """List approved leads ready to send, with their final message text."""
    with store.connect() as conn:
        leads = store.list_leads(conn, status="approved")
        if not leads:
            console.print("No approved leads waiting to be sent.")
            return
        for lead in leads:
            console.print(
                Panel(
                    f"[bold]{lead.author}[/] ({lead.group_name})\n"
                    f"{lead.post_url}\n\n{lead.draft_message}",
                    title=f"Lead #{lead.id} — send this",
                )
            )


def main() -> None:
    parser = argparse.ArgumentParser(description="TLV apartment sublet lead agent")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("login", help="Log into Facebook and save the session").set_defaults(func=cmd_login)

    scan_parser = sub.add_parser("scan", help="Scan configured groups for new leads")
    scan_parser.add_argument(
        "--headed", action="store_true", help="Show the browser window while scanning"
    )
    scan_parser.set_defaults(func=cmd_scan)

    sub.add_parser("review", help="Review new leads one by one").set_defaults(func=cmd_review)
    sub.add_parser("approved", help="List approved leads ready to send").set_defaults(func=cmd_approved)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    sys.exit(main())
