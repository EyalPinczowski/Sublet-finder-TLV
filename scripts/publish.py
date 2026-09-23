#!/usr/bin/env python3
"""Renders a self-contained static HTML snapshot of your matched listings
and pushes it to a DEDICATED repo (SITE_REPO_URL in .env) for GitHub Pages
— NEVER this code repo, so addresses/prices never land in its git history.

SITE_REPO_URL is read lazily (like sheets.py's GOOGLE_SHEET_ID), so an
unset value just prints one line and does nothing.

The published page carries a noindex hint for search engines, but it is
still reachable by anyone with the URL — GitHub Pages on a public repo has
no access control. See README "Publishing a snapshot" before using this.

Usage: python scripts/publish.py
"""
from __future__ import annotations

import html
import os
import subprocess
from datetime import datetime
from pathlib import Path

import _bootstrap  # noqa: F401

from src import store

SITE_DIR = Path(__file__).resolve().parent.parent / "data" / "site"


def _card(conn, row) -> str:
    score = store.effective_score(conn, row)
    images = row.image_urls()
    img_html = f'<img src="{html.escape(images[0])}">' if images else ""
    post_link = (
        f'<a href="{html.escape(row.post_url)}">View post</a>'
        if row.post_url.startswith("http")
        else ""
    )
    profiles = ", ".join(row.profile_names()) or "?"
    stay = " &middot; ".join(
        part
        for part in [
            row.lease_start_date and f"from {row.lease_start_date}",
            row.lease_duration_days and f"{row.lease_duration_days} days",
        ]
        if part
    )
    stay_html = f'<p class="stay">{html.escape(stay)}</p>' if stay else ""
    return (
        f'<div class="card">{img_html}'
        f"<h3>{f'{row.price} ILS' if row.price is not None else 'Price not listed'} "
        f"&middot; {row.rooms or '?'} rooms &middot; score {score}</h3>"
        f'<p class="matched">Matched: {html.escape(profiles)}</p>'
        f"{stay_html}"
        f'<p class="addr">{html.escape(row.address or row.neighborhoods or "area unknown")}</p>'
        f"<p>{html.escape(row.summary or row.raw_text[:200])}</p>"
        f"<p>{html.escape(row.phone or '')}</p>"
        f"{post_link}</div>"
    )


def render_snapshot(conn) -> str:
    rows = store.list_listings(conn, matched_only=True)
    rows.sort(key=lambda r: store.effective_score(conn, r), reverse=True)
    cards = "".join(_card(conn, row) for row in rows) or "<p>No matches yet.</p>"
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><meta name="robots" content="noindex">
<title>TLV Sublet Matches</title>
<style>
body {{ font-family: sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; }}
.card {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
.addr {{ font-weight: bold; }}
.matched {{ display: inline-block; background: #eef; border-radius: 4px; padding: 0.1rem 0.5rem;
            font-size: 0.85em; }}
img {{ max-width: 100%; border-radius: 4px; }}
</style></head>
<body>
<h1>TLV Sublet Matches</h1>
<p>Generated {generated}</p>
{cards}
</body></html>"""


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True)


def publish() -> None:
    repo_url = os.environ.get("SITE_REPO_URL")
    if not repo_url:
        print("[publish] SITE_REPO_URL not set — skipping.")
        return

    with store.connect() as conn:
        snapshot = render_snapshot(conn)

    if not (SITE_DIR / ".git").exists():
        SITE_DIR.parent.mkdir(parents=True, exist_ok=True)
        result = _run("git", "clone", repo_url, str(SITE_DIR))
        if result.returncode != 0:
            print(f"[publish] could not clone {repo_url}: {result.stderr.strip()}")
            return
    else:
        result = _run("git", "-C", str(SITE_DIR), "pull", "--ff-only")
        if result.returncode != 0:
            print(f"[publish] could not pull the site repo: {result.stderr.strip()}")
            return

    (SITE_DIR / "index.html").write_text(snapshot, encoding="utf-8")

    _run("git", "-C", str(SITE_DIR), "add", "index.html")
    commit = _run("git", "-C", str(SITE_DIR), "commit", "-m", "Update listings snapshot")
    if commit.returncode != 0:
        if "nothing to commit" in (commit.stdout + commit.stderr):
            print("[publish] no changes since the last snapshot.")
        else:
            print(f"[publish] commit failed: {commit.stderr.strip()}")
        return

    push = _run("git", "-C", str(SITE_DIR), "push")
    if push.returncode != 0:
        print(f"[publish] push failed: {push.stderr.strip()}")
        return
    print("[publish] pushed a new snapshot.")


if __name__ == "__main__":
    publish()
