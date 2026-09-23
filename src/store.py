from __future__ import annotations

import hashlib
import json
import re
import secrets
import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "listings.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_url TEXT UNIQUE NOT NULL,
    group_name TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    price INTEGER,
    rooms REAL,
    neighborhoods TEXT,  -- comma-joined
    roommates INTEGER,
    toilets INTEGER,
    available_rooms INTEGER,
    lease_start_date TEXT,
    lease_end_date TEXT,
    lease_duration_days INTEGER,
    address TEXT,
    phone TEXT,
    images TEXT,  -- JSON-encoded list of URLs
    summary TEXT,
    lat REAL,
    lon REAL,
    distance_m REAL,
    score INTEGER,
    content_hash TEXT,
    phone_hash TEXT,  -- second fuzzy-repost signal: phone+price+rooms
    matched INTEGER NOT NULL DEFAULT 0,  -- 1 if it matched ANY search profile
    matched_profiles TEXT,  -- comma-joined names of every profile it matched
    notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_listings_content_hash ON listings(content_hash);
-- idx_listings_phone_hash is created in _ensure_schema_upgrades() below,
-- not here — on a pre-existing DB from before phone_hash existed, this
-- executescript() runs BEFORE that migration, so an index on the column
-- here would fail with "no such column: phone_hash".

-- Per-user ⭐ save / 🗑 dismiss votes from Telegram/dashboard buttons. A save
-- nudges the listing's effective score; a dismiss hides it without deleting
-- the row. Keyed by post_url, this tool's natural dedup identity (a real
-- permalink, or the synthetic text-signature key scraper.py falls back to).
CREATE TABLE IF NOT EXISTS marks (
    post_url TEXT NOT NULL,
    user_id TEXT NOT NULL,
    mark TEXT NOT NULL,  -- "save" or "dismiss"
    ts TEXT DEFAULT (datetime('now')),
    PRIMARY KEY (post_url, user_id)
);

-- Short stand-ins for a post_url inside a Telegram callback_data payload
-- (Telegram caps it at 64 UTF-8 bytes and rejects the whole message if any
-- button exceeds that; a Hebrew-heavy URL/text-signature key can overflow).
CREATE TABLE IF NOT EXISTS callback_tokens (
    token TEXT PRIMARY KEY,
    post_url TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_callback_tokens_url ON callback_tokens(post_url);
"""

MARK_SCORE_DELTA = 25


@dataclass
class ListingRow:
    id: int
    post_url: str
    group_name: str
    raw_text: str
    price: int | None
    rooms: float | None
    neighborhoods: str | None
    roommates: int | None
    toilets: int | None
    available_rooms: int | None
    lease_start_date: str | None
    lease_end_date: str | None
    lease_duration_days: int | None
    address: str | None
    phone: str | None
    images: str | None
    summary: str | None
    lat: float | None
    lon: float | None
    distance_m: float | None
    score: int | None
    content_hash: str | None
    phone_hash: str | None
    matched: int
    matched_profiles: str | None
    notified: int
    created_at: str

    def image_urls(self) -> list[str]:
        try:
            return json.loads(self.images) if self.images else []
        except json.JSONDecodeError:
            return []

    def profile_names(self) -> list[str]:
        return [n for n in (self.matched_profiles or "").split(", ") if n]


def _ensure_schema_upgrades(conn) -> None:
    """SCHEMA's CREATE TABLE IF NOT EXISTS is a no-op against a DB that
    already has the `listings` table from before a new column existed —
    this adds any such column by hand so an existing data/listings.db
    (already populated with real matches) doesn't break on the next
    insert_listing() call."""
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(listings)")}
    if "phone_hash" not in cols:
        conn.execute("ALTER TABLE listings ADD COLUMN phone_hash TEXT")
    # Safe to (re)create unconditionally: the column now exists either way
    # (just added above, or already present from a fresh CREATE TABLE).
    conn.execute("CREATE INDEX IF NOT EXISTS idx_listings_phone_hash ON listings(phone_hash)")


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        _ensure_schema_upgrades(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def listing_seen(conn, post_url: str) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE post_url = ?", (post_url,)).fetchone()
    return row is not None


def content_hash_key(listing) -> str | None:
    """A fuzzy fallback identity from a listing's own content (address +
    price + rooms), for catching the same flat reposted under a different
    permalink/text — mirrors bgu-housing-bot's _content_hash_key. None when
    there's no address: price/rooms alone are far too common to treat as a
    duplicate signal, and without this every address-less listing would
    hash identically and collapse into "duplicates" of the first one seen."""
    if not listing.address:
        return None
    basis = f"{listing.address.strip().lower()}|{listing.price}|{listing.rooms}"
    return "hash:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def find_by_content_hash(conn, content_hash: str) -> str | None:
    """The post_url of an existing row with the same content hash, if any —
    a likely repost of a listing already stored under a different key."""
    if not content_hash:
        return None
    row = conn.execute(
        "SELECT post_url FROM listings WHERE content_hash = ? LIMIT 1", (content_hash,)
    ).fetchone()
    return row["post_url"] if row else None


def phone_hash_key(listing) -> str | None:
    """A second fuzzy-repost signal alongside content_hash_key, keyed on
    phone number + price + rooms (digits only, so formatting differences
    don't matter) instead of address — catches the same listing reworded
    with different address text but the same contact number. None when
    there's no phone, for the same reason content_hash_key requires an
    address: price/rooms alone are far too common to treat as a duplicate
    signal on their own."""
    if not listing.phone:
        return None
    digits = re.sub(r"\D", "", listing.phone)
    if not digits:
        return None
    basis = f"{digits}|{listing.price}|{listing.rooms}"
    return "phone:" + hashlib.sha1(basis.encode("utf-8")).hexdigest()[:16]


def find_by_phone_hash(conn, phone_hash: str | None) -> str | None:
    """The post_url of an existing row with the same phone hash, if any —
    a likely repost of a listing already stored under a different key."""
    if not phone_hash:
        return None
    row = conn.execute(
        "SELECT post_url FROM listings WHERE phone_hash = ? LIMIT 1", (phone_hash,)
    ).fetchone()
    return row["post_url"] if row else None


def insert_listing(
    conn,
    listing,
    matched_profiles: list[str],
    content_hash: str | None = None,
    phone_hash: str | None = None,
) -> int | None:
    """content_hash/phone_hash default to recomputing from `listing` when
    omitted, but a caller that already computed them (e.g. cli.py's _scan,
    which needs them beforehand anyway to check find_by_content_hash/
    find_by_phone_hash) should pass them in to avoid hashing twice."""
    if content_hash is None:
        content_hash = content_hash_key(listing)
    if phone_hash is None:
        phone_hash = phone_hash_key(listing)
    cur = conn.execute(
        "INSERT OR IGNORE INTO listings "
        "(post_url, group_name, raw_text, price, rooms, neighborhoods, "
        " roommates, toilets, available_rooms, lease_start_date, lease_end_date, "
        " lease_duration_days, address, phone, images, summary, lat, lon, "
        " distance_m, score, content_hash, phone_hash, matched, matched_profiles) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            listing.post_url,
            listing.group_name,
            listing.raw_text,
            listing.price,
            listing.rooms,
            ", ".join(listing.neighborhoods_mentioned),
            listing.roommates,
            listing.toilets,
            listing.available_rooms,
            listing.lease_start_date.isoformat() if listing.lease_start_date else None,
            listing.lease_end_date.isoformat() if listing.lease_end_date else None,
            listing.lease_duration_days,
            listing.address,
            listing.phone,
            json.dumps(listing.images or []),
            listing.summary,
            listing.lat,
            listing.lon,
            listing.distance_m,
            listing.score,
            content_hash,
            phone_hash,
            1 if matched_profiles else 0,
            ", ".join(matched_profiles),
        ),
    )
    # cur.lastrowid isn't None when INSERT OR IGNORE hits the UNIQUE
    # constraint — sqlite3 leaves it at the last successful insert on this
    # connection. rowcount is the reliable "did this statement insert a row"
    # signal callers (cli.py) need to detect a duplicate race.
    return cur.lastrowid if cur.rowcount > 0 else None


def mark_listing_notified(conn, listing_id: int) -> None:
    conn.execute("UPDATE listings SET notified = 1 WHERE id = ?", (listing_id,))


def recent_matched_http_urls(conn, limit: int) -> list[str]:
    """post_urls of the most-recently-matched, still-visible (not
    dismissed/dead), real-link listings — a lightweight alternative to
    list_listings() for a caller (dead-link pruning) that only needs the
    URL and a small capped batch, not every column of the whole match
    history."""
    rows = conn.execute(
        "SELECT l.post_url FROM listings l WHERE l.matched = 1 "
        "AND l.post_url LIKE 'http%' AND NOT EXISTS ("
        "  SELECT 1 FROM marks m WHERE m.post_url = l.post_url AND m.mark = 'dismiss'"
        # id DESC as a tiebreaker: created_at has only second precision, so
        # several rows inserted within the same second would otherwise sort
        # arbitrarily rather than newest-first.
        ") ORDER BY l.created_at DESC, l.id DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [row["post_url"] for row in rows]


def list_listings(
    conn, matched_only: bool = True, include_dismissed: bool = False
) -> list[ListingRow]:
    query = "SELECT * FROM listings WHERE 1=1"
    params: list = []
    if matched_only:
        query += " AND matched = 1"
    query += " ORDER BY score DESC, created_at DESC"
    rows = conn.execute(query, params).fetchall()
    listings = [ListingRow(**dict(r)) for r in rows]
    if include_dismissed:
        return listings
    dismissed = _dismissed_post_urls(conn)
    return [row for row in listings if row.post_url not in dismissed]


# --- votes: ⭐ save / 🗑 dismiss (Telegram buttons and the dashboard) ---


def add_mark(conn, post_url: str, user_id: str, mark: str) -> None:
    conn.execute(
        "INSERT INTO marks (post_url, user_id, mark) VALUES (?, ?, ?) "
        "ON CONFLICT (post_url, user_id) DO UPDATE SET mark = excluded.mark, "
        "ts = datetime('now')",
        (post_url, user_id, mark),
    )


_DEAD_LINK_USER_ID = "dead-link-check"


def mark_listing_dead(conn, post_url: str) -> None:
    """Facebook no longer shows this post (rented out / removed) — reuses
    the existing dismiss mechanism under a distinct synthetic user_id, so
    it's filtered out by list_listings()/is_dismissed() the same way a
    human's dismiss is, without a new column or a separate exclusion path."""
    add_mark(conn, post_url, _DEAD_LINK_USER_ID, "dismiss")


def _dismissed_post_urls(conn) -> set[str]:
    """Every post_url with a dismiss mark, in one query — the batch form
    list_listings() uses instead of an is_dismissed() call per row."""
    rows = conn.execute("SELECT DISTINCT post_url FROM marks WHERE mark = 'dismiss'").fetchall()
    return {row["post_url"] for row in rows}


def is_dismissed(conn, post_url: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM marks WHERE post_url = ? AND mark = 'dismiss' LIMIT 1", (post_url,)
    ).fetchone()
    return row is not None


def save_count(conn, post_url: str) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS n FROM marks WHERE post_url = ? AND mark = 'save'", (post_url,)
    ).fetchone()
    return row["n"] if row else 0


def _save_counts(conn) -> dict[str, int]:
    """Every post_url's save count, in one query — the batch form
    effective_scores() uses instead of a save_count() call per row."""
    rows = conn.execute(
        "SELECT post_url, COUNT(*) AS n FROM marks WHERE mark = 'save' GROUP BY post_url"
    ).fetchall()
    return {row["post_url"]: row["n"] for row in rows}


def effective_score(conn, row: ListingRow) -> int:
    """The stored fit score plus MARK_SCORE_DELTA per ⭐ save — intentionally
    uncapped past 100, so a well-endorsed listing can read above 100 rather
    than being swallowed by the ceiling (mirrors bgu's approach). For a
    single listing (e.g. right after inserting or voting on it); a caller
    scoring/sorting a whole list_listings() result should use
    effective_scores() instead — one query total rather than one per row."""
    base = row.score or 0
    return base + save_count(conn, row.post_url) * MARK_SCORE_DELTA


def effective_scores(conn, rows: list[ListingRow]) -> dict[str, int]:
    """effective_score() for a whole list of rows in one batch query
    (keyed by post_url) instead of one save_count() query per row —
    use this for sorting/displaying a list_listings() result."""
    counts = _save_counts(conn)
    return {
        row.post_url: (row.score or 0) + counts.get(row.post_url, 0) * MARK_SCORE_DELTA
        for row in rows
    }


# --- callback tokens: short stand-ins for post_url in Telegram buttons ---


def callback_token(conn, post_url: str) -> str:
    row = conn.execute(
        "SELECT token FROM callback_tokens WHERE post_url = ? LIMIT 1", (post_url,)
    ).fetchone()
    if row:
        return row["token"]
    token = secrets.token_urlsafe(8)
    conn.execute(
        "INSERT INTO callback_tokens (token, post_url) VALUES (?, ?)", (token, post_url)
    )
    return token


def post_url_for_token(conn, token: str) -> str | None:
    row = conn.execute(
        "SELECT post_url FROM callback_tokens WHERE token = ? LIMIT 1", (token,)
    ).fetchone()
    return row["post_url"] if row else None
