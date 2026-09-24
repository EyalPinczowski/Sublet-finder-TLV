"""Shared dashboard connection details — read by scripts/dashboard.py
itself (what to bind to) and by telegram_notifier.py/sheets.py (how to
build a link to it from elsewhere, e.g. a Telegram button)."""
from __future__ import annotations

import os
import secrets
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# This module reads DASHBOARD_HOST/DASHBOARD_PORT/DASHBOARD_TOKEN directly
# from the environment, so it needs .env loaded itself rather than relying
# on some other module (e.g. src.config) having been imported first —
# scripts/dashboard.py's import chain doesn't otherwise touch src.config,
# so without this, .env's values were silently ignored.
load_dotenv(ROOT / ".env")

TOKEN_PATH = ROOT / "data" / "dashboard_token.txt"
DEFAULT_PORT = 8765


def get_host() -> str:
    """Defaults to 127.0.0.1 — LAN/local-only, matching
    scripts/dashboard.py's own default bind address. Set DASHBOARD_HOST
    to your tablet's LAN IP (e.g. 192.168.1.23) to make the dashboard
    reachable from your phone over WiFi, and to make a "Dashboard" link
    elsewhere (a Telegram button, a Sheets cell) actually work. Never set
    this to 0.0.0.0 or a public IP — the dashboard has no auth beyond one
    token in the query string, and it shows addresses/phone numbers."""
    return os.environ.get("DASHBOARD_HOST", "127.0.0.1")


def get_port() -> int:
    try:
        return int(os.environ.get("DASHBOARD_PORT", DEFAULT_PORT))
    except ValueError:
        return DEFAULT_PORT


def get_token() -> str:
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


def dashboard_url() -> str | None:
    """None while DASHBOARD_HOST is still the default 127.0.0.1 — a link
    to that address would only actually load if tapped from the very
    same device running the dashboard, which is misleading everywhere
    else (a phone's 127.0.0.1 is the phone itself, not your tablet), so
    the link is simply omitted until you've set DASHBOARD_HOST to
    something reachable from wherever you'll tap it."""
    host = get_host()
    if host == "127.0.0.1":
        return None
    return f"http://{host}:{get_port()}/?token={get_token()}"
