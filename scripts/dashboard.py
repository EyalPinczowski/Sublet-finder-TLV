#!/usr/bin/env python3
"""A small local dashboard: reads SQLite live and lists matched listings
sorted by effective score (fit score + vote nudges), with the same
⭐ Save / \U0001f5d1 Dismiss actions as the Telegram alerts.

Every route requires DASHBOARD_TOKEN in the query string (auto-generated
into data/dashboard_token.txt on first run if you don't set one) — there is
no unauthenticated mode, since listings carry addresses and phone numbers.
Binds to 127.0.0.1 only: LAN/local-only by design, never expose this port
to the internet. For access away from your network, see scripts/publish.py.

Usage: python scripts/dashboard.py [--port 8765]
"""
from __future__ import annotations

import argparse
import html
import os
import secrets
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlparse

import _bootstrap  # noqa: F401

from src import store

TOKEN_PATH = Path(__file__).resolve().parent.parent / "data" / "dashboard_token.txt"


def _get_token() -> str:
    token = os.environ.get("DASHBOARD_TOKEN")
    if token:
        return token
    if TOKEN_PATH.exists():
        return TOKEN_PATH.read_text().strip()
    token = secrets.token_urlsafe(16)
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    TOKEN_PATH.write_text(token)
    print(f"Generated a dashboard token and saved it to {TOKEN_PATH}")
    return token


def _card(conn, row, token: str) -> str:
    score = store.effective_score(conn, row)
    images = row.image_urls()
    img_html = f'<img src="{html.escape(images[0])}">' if images else ""
    post_link = (
        f'<a href="{html.escape(row.post_url)}" target="_blank">View post</a>'
        if row.post_url.startswith("http")
        else ""
    )
    post_q = quote(row.post_url, safe="")
    profiles = ", ".join(row.profile_names()) or "?"
    price = f"{row.price} ILS" if row.price is not None else "Price not listed"
    return f"""
    <div class="card">
      {img_html}
      <h3>{price} &middot; {row.rooms or '?'} rooms &middot; score {score}</h3>
      <p class="matched">Matched: {html.escape(profiles)}</p>
      <p class="addr">{html.escape(row.address or row.neighborhoods or 'area unknown')}</p>
      <p>{html.escape(row.summary or row.raw_text[:200])}</p>
      <p>{html.escape(row.phone or '')}</p>
      {post_link}
      <p class="actions">
        <a href="/vote?token={token}&amp;action=save&amp;post={post_q}">⭐ Save</a>
        &nbsp;
        <a href="/vote?token={token}&amp;action=dismiss&amp;post={post_q}">\U0001f5d1 Dismiss</a>
      </p>
    </div>
    """


def render_page(conn, token: str) -> str:
    rows = store.list_listings(conn, matched_only=True)
    rows.sort(key=lambda r: store.effective_score(conn, r), reverse=True)
    cards = "".join(_card(conn, row, token) for row in rows) or "<p>No matches yet.</p>"
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>TLV Sublet Matches</title>
<style>
body {{ font-family: sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; }}
.card {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
.addr {{ font-weight: bold; }}
.matched {{ display: inline-block; background: #eef; border-radius: 4px; padding: 0.1rem 0.5rem;
            font-size: 0.85em; }}
img {{ max-width: 100%; border-radius: 4px; }}
.actions a {{ text-decoration: none; }}
</style></head>
<body>
<h1>TLV Sublet Matches ({len(rows)})</h1>
{cards}
</body></html>"""


def make_handler(token: str):
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            parsed = urlparse(self.path)
            params = parse_qs(parsed.query)
            if params.get("token", [""])[0] != token:
                self.send_response(403)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Forbidden: missing or invalid ?token=")
                return

            if parsed.path == "/vote":
                action = params.get("action", [""])[0]
                post = params.get("post", [""])[0]
                if action in ("save", "dismiss") and post:
                    with store.connect() as conn:
                        store.add_mark(conn, post, "dashboard", action)
                self.send_response(302)
                self.send_header("Location", f"/?token={token}")
                self.end_headers()
                return

            with store.connect() as conn:
                page = render_page(conn, token)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def log_message(self, fmt, *args):  # quiet the default stderr access log
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    token = _get_token()
    server = HTTPServer(("127.0.0.1", args.port), make_handler(token))
    print(f"Dashboard: http://127.0.0.1:{args.port}/?token={token}")
    print("LAN/local-only by design — do not expose this port to the internet.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
