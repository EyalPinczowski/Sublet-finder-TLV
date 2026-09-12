from __future__ import annotations

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
    matched INTEGER NOT NULL DEFAULT 0,  -- 1 if it passed your search filters
    notified INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


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
    matched: int
    notified: int


@contextmanager
def connect():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def listing_seen(conn, post_url: str) -> bool:
    row = conn.execute("SELECT 1 FROM listings WHERE post_url = ?", (post_url,)).fetchone()
    return row is not None


def insert_listing(conn, listing, matched: bool) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO listings "
        "(post_url, group_name, raw_text, price, rooms, neighborhoods, "
        " roommates, toilets, matched) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            listing.post_url,
            listing.group_name,
            listing.raw_text,
            listing.price,
            listing.rooms,
            ", ".join(listing.neighborhoods_mentioned),
            listing.roommates,
            listing.toilets,
            1 if matched else 0,
        ),
    )
    return cur.lastrowid


def mark_listing_notified(conn, listing_id: int) -> None:
    conn.execute("UPDATE listings SET notified = 1 WHERE id = ?", (listing_id,))


def list_listings(conn, matched_only: bool = True) -> list[ListingRow]:
    query = "SELECT * FROM listings WHERE 1=1"
    params: list = []
    if matched_only:
        query += " AND matched = 1"
    query += " ORDER BY created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [ListingRow(**dict(r)) for r in rows]
