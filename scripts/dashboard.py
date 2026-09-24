#!/usr/bin/env python3
"""A small local dashboard: reads SQLite live and lists matched listings
sorted by effective score (fit score + vote nudges), with the same
⭐ Save / \U0001f5d1 Dismiss actions as the Telegram alerts.

Every route requires DASHBOARD_TOKEN in the query string (auto-generated
into data/dashboard_token.txt on first run if you don't set one) — there is
no unauthenticated mode, since listings carry addresses and phone numbers.
Binds to 127.0.0.1 by default: LAN/local-only, never expose this port to
the internet. Set DASHBOARD_HOST to your tablet's LAN IP to make it (and
the "Dashboard" links in Telegram/Sheets) reachable from your phone over
WiFi. For access away from your network, see scripts/publish.py.

Usage: python scripts/dashboard.py [--port 8765]
"""
from __future__ import annotations

import argparse
import html
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import _bootstrap  # noqa: F401

from src import store
from src.contact import PRICE_INQUIRY_MESSAGE, whatsapp_link
from src.dashboard_config import get_host, get_port
from src.dashboard_config import get_token as _get_token
from src.geocode import map_url as build_map_url


def _is_small(available_rooms: int | None) -> bool:
    """1-2 available rooms — small enough to be worth calling out
    separately, both as a distinct marker color on the map and a badge
    on each card."""
    return available_rooms in (1, 2)


def _suitable_label(available_rooms: int | None) -> str:
    if available_rooms is None:
        return ""
    if available_rooms == 1:
        return "1 person"
    return f"{available_rooms} people"


def _suitable_badge_html(available_rooms: int | None) -> str:
    label = _suitable_label(available_rooms)
    if not label:
        return ""
    css_class = "suitable-small" if _is_small(available_rooms) else "suitable-other"
    return f'<span class="{css_class}">{html.escape(label)}</span>'


def _card(row, token: str, score: int) -> str:
    images = row.image_urls()
    img_html = f'<img src="{html.escape(images[0])}">' if images else ""
    post_link = (
        f'<a href="{html.escape(row.post_url)}" target="_blank" rel="noreferrer">View post</a>'
        if row.post_url.startswith("http")
        else ""
    )
    map_link = build_map_url(row.address, row.lat, row.lon)
    map_link_html = (
        f' &middot; <a href="{html.escape(map_link)}" target="_blank" '
        'rel="noreferrer">Google Maps</a>'
        if map_link
        else ""
    )
    # Pre-filled price inquiry when the price is still unknown (a
    # "potential match" is unverified precisely because of that), a
    # plain "open the chat" link otherwise — same rule as the Telegram
    # alert's WhatsApp button.
    wa_message = PRICE_INQUIRY_MESSAGE if row.price is None else None
    wa_link = whatsapp_link(row.phone, message=wa_message)
    wa_label = "Ask about price" if row.price is None else "Contact via WhatsApp"
    wa_link_html = (
        f' &middot; <a href="{html.escape(wa_link)}" target="_blank" '
        f'rel="noreferrer">\U0001F4AC {wa_label}</a>'
        if wa_link
        else ""
    )
    profiles = ", ".join(row.profile_names()) or "?"
    price = f"{row.price} ILS" if row.price is not None else "Price not listed"
    # Price is a soft filter — a listing with no stated price still shows
    # up here, but was never actually confirmed to be in budget.
    potential_html = "" if row.price is not None else '<span class="potential">potential</span>'
    suitable_html = _suitable_badge_html(row.available_rooms)
    stay = " &middot; ".join(
        part
        for part in [
            row.lease_start_date and f"from {row.lease_start_date}",
            row.lease_duration_days and f"{row.lease_duration_days} days",
        ]
        if part
    )
    stay_html = f'<p class="stay">{html.escape(stay)}</p>' if stay else ""
    save_form = _vote_form(token, row.post_url, "save", "⭐ Save")
    dismiss_form = _vote_form(token, row.post_url, "dismiss", "\U0001f5d1 Dismiss")
    return f"""
    <div class="card">
      {img_html}
      <h3>{price}{potential_html} &middot; {row.rooms or '?'} rooms &middot; score {score}</h3>
      <p class="matched">Matched: {html.escape(profiles)}</p>{suitable_html}
      {stay_html}
      <p class="addr">{html.escape(row.address or row.neighborhoods or 'area unknown')}</p>
      <p>{html.escape(row.summary or row.raw_text[:200])}</p>
      <p>{html.escape(row.phone or '')}</p>
      {post_link}{map_link_html}{wa_link_html}
      <p class="actions">
        {save_form}
        {dismiss_form}
      </p>
    </div>
    """


def _vote_form(token: str, post_url: str, action: str, label: str) -> str:
    # POST, not a GET link — a GET /vote used to mutate state, which meant
    # a leaked dashboard URL (the token IS the auth, carried right there in
    # the URL — see the module docstring) could be silently exploited by
    # any link-prefetcher or crawler just following the Save/Dismiss links,
    # no click needed. A POST form isn't prefetched or auto-followed.
    return (
        '<form method="post" action="/vote" style="display:inline">'
        f'<input type="hidden" name="token" value="{html.escape(token)}">'
        f'<input type="hidden" name="action" value="{html.escape(action)}">'
        f'<input type="hidden" name="post" value="{html.escape(post_url)}">'
        f'<button type="submit" class="link-btn">{label}</button>'
        "</form>"
    )


# Leaflet + OpenStreetMap: no API key needed, unlike the Google Maps JS
# API — fits this project's existing "free, no-key" pattern (geocode.py's
# own Nominatim use). Markers still deep-link out to Google Maps/the
# original post; only the map widget itself is Leaflet.
_MAP_SCRIPT_TEMPLATE = """
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<div id="map" style="height:420px;border-radius:8px;margin-bottom:1.5rem;"></div>
<script>
const markers = __MARKERS_JSON__;
const map = L.map('map').setView([32.0768, 34.7742], 13);
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
  maxZoom: 19,
  attribution: '&copy; OpenStreetMap contributors'
}).addTo(map);
const bounds = [];
markers.forEach(function (m) {
  const color = m.category === 'small' ? '#2ecc71' : '#3498db';
  const marker = L.circleMarker([m.lat, m.lon], {
    radius: 8, color: color, fillColor: color, fillOpacity: 0.85, weight: 2
  }).addTo(map);
  let popup = '<b>' + m.price_label + '</b> &middot; score ' + m.score;
  if (m.suitable) { popup += '<br>' + m.suitable; }
  if (m.post_url) {
    popup += '<br><a href="' + m.post_url + '" target="_blank" rel="noreferrer">View post</a>';
  }
  if (m.map_link) {
    popup += ' &middot; <a href="' + m.map_link + '" target="_blank" ' +
      'rel="noreferrer">Google Maps</a>';
  }
  marker.bindPopup(popup);
  bounds.push([m.lat, m.lon]);
});
if (bounds.length) { map.fitBounds(bounds, { padding: [30, 30] }); }
</script>
"""


def _map_markers(rows, scores: dict) -> list[dict]:
    """One entry per matched listing with known coordinates — listings
    without a geocoded address just don't get a marker, same as they
    already don't get a distance score."""
    markers = []
    for row in rows:
        if row.lat is None or row.lon is None:
            continue
        markers.append(
            {
                "lat": row.lat,
                "lon": row.lon,
                "price_label": f"{row.price} ILS" if row.price is not None else "Price not listed",
                "score": scores[row.post_url],
                "suitable": _suitable_label(row.available_rooms),
                "post_url": row.post_url if row.post_url.startswith("http") else "",
                "map_link": build_map_url(row.address, row.lat, row.lon) or "",
                "category": "small" if _is_small(row.available_rooms) else "other",
            }
        )
    return markers


def _render_map(rows, scores: dict) -> str:
    markers = _map_markers(rows, scores)
    if not markers:
        return ""
    # json.dumps() already escapes for safe embedding in a <script> tag;
    # the extra "<" escape guards against a "</script" sequence hiding in
    # an address/summary string from ending the tag early.
    markers_json = json.dumps(markers).replace("<", "\\u003c")
    return _MAP_SCRIPT_TEMPLATE.replace("__MARKERS_JSON__", markers_json)


def render_page(conn, token: str) -> str:
    rows = store.list_listings(conn, matched_only=True)
    scores = store.effective_scores(conn, rows)
    rows.sort(key=lambda r: scores[r.post_url], reverse=True)
    map_html = _render_map(rows, scores)
    cards = (
        "".join(_card(row, token, scores[row.post_url]) for row in rows)
        or "<p>No matches yet.</p>"
    )
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>TLV Sublet Matches</title>
<style>
body {{ font-family: sans-serif; max-width: 700px; margin: 2rem auto; padding: 0 1rem; }}
.card {{ border: 1px solid #ccc; border-radius: 8px; padding: 1rem; margin-bottom: 1rem; }}
.addr {{ font-weight: bold; }}
.matched {{ display: inline-block; background: #eef; border-radius: 4px; padding: 0.1rem 0.5rem;
            font-size: 0.85em; }}
.suitable-small {{ display: inline-block; background: #d4f7dc; color: #1b7a34; border-radius: 4px;
                    padding: 0.1rem 0.5rem; font-size: 0.85em; margin-left: 0.4rem; }}
.suitable-other {{ display: inline-block; background: #eef; color: #334; border-radius: 4px;
                    padding: 0.1rem 0.5rem; font-size: 0.85em; margin-left: 0.4rem; }}
.potential {{ display: inline-block; background: #fff3cd; color: #8a6500; border-radius: 4px;
              padding: 0.1rem 0.5rem; font-size: 0.7em; margin-left: 0.4rem;
              vertical-align: middle; }}
img {{ max-width: 100%; border-radius: 4px; }}
.actions a {{ text-decoration: none; }}
.actions form {{ display: inline; }}
.link-btn {{ background: none; border: none; padding: 0; font: inherit; color: #06c;
             text-decoration: none; cursor: pointer; }}
</style></head>
<body>
<h1>TLV Sublet Matches ({len(rows)})</h1>
{map_html}
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
                # Save/Dismiss is a POST-only mutation — see _vote_form and
                # do_POST. A GET here used to silently mutate state, which
                # meant a leaked dashboard link could be exploited by any
                # crawler/prefetcher just following it, no click needed.
                self.send_response(405)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Method Not Allowed: /vote requires POST")
                return

            with store.connect() as conn:
                page = render_page(conn, token)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode("utf-8"))

        def do_POST(self):
            parsed = urlparse(self.path)
            if parsed.path != "/vote":
                self.send_response(404)
                self.end_headers()
                return

            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length).decode("utf-8") if length else ""
            params = parse_qs(body)
            if params.get("token", [""])[0] != token:
                self.send_response(403)
                self.send_header("Content-Type", "text/plain; charset=utf-8")
                self.end_headers()
                self.wfile.write(b"Forbidden: missing or invalid token")
                return

            action = params.get("action", [""])[0]
            post = params.get("post", [""])[0]
            if action in ("save", "dismiss") and post:
                with store.connect() as conn:
                    store.add_mark(conn, post, "dashboard", action)
            self.send_response(302)
            self.send_header("Location", f"/?token={token}")
            self.end_headers()

        def log_message(self, fmt, *args):  # quiet the default stderr access log
            pass

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=get_port())
    args = parser.parse_args()

    host = get_host()
    token = _get_token()
    server = HTTPServer((host, args.port), make_handler(token))
    print(f"Dashboard: http://{host}:{args.port}/?token={token}")
    if host == "127.0.0.1":
        print("LAN/local-only by design — do not expose this port to the internet.")
    else:
        print(
            f"Bound to {host} (DASHBOARD_HOST) — reachable from your LAN. "
            "Never set this to a public/internet-facing address."
        )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
