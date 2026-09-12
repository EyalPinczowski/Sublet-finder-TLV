from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "leads.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS leads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    post_url TEXT UNIQUE NOT NULL,
    group_name TEXT NOT NULL,
    author TEXT,
    post_text TEXT NOT NULL,
    fit_score INTEGER,
    screening_notes TEXT,
    draft_message TEXT,
    status TEXT NOT NULL DEFAULT 'new',  -- new | approved | rejected | sent
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@dataclass
class Lead:
    id: int
    post_url: str
    group_name: str
    author: str
    post_text: str
    fit_score: int | None
    screening_notes: str | None
    draft_message: str | None
    status: str


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


def post_seen(conn, post_url: str) -> bool:
    row = conn.execute("SELECT 1 FROM leads WHERE post_url = ?", (post_url,)).fetchone()
    return row is not None


def insert_raw_post(conn, post_url: str, group_name: str, author: str, post_text: str) -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO leads (post_url, group_name, author, post_text) "
        "VALUES (?, ?, ?, ?)",
        (post_url, group_name, author, post_text),
    )
    return cur.lastrowid


def update_screening(conn, lead_id: int, fit_score: int, notes: str) -> None:
    conn.execute(
        "UPDATE leads SET fit_score = ?, screening_notes = ? WHERE id = ?",
        (fit_score, notes, lead_id),
    )


def update_draft(conn, lead_id: int, draft_message: str) -> None:
    conn.execute(
        "UPDATE leads SET draft_message = ? WHERE id = ?",
        (draft_message, lead_id),
    )


def set_status(conn, lead_id: int, status: str) -> None:
    conn.execute("UPDATE leads SET status = ? WHERE id = ?", (status, lead_id))


def get_lead(conn, lead_id: int) -> Lead | None:
    row = conn.execute("SELECT * FROM leads WHERE id = ?", (lead_id,)).fetchone()
    return Lead(**dict(row)) if row else None


def list_leads(conn, status: str | None = None, min_fit_score: int | None = None) -> list[Lead]:
    query = "SELECT * FROM leads WHERE 1=1"
    params: list = []
    if status:
        query += " AND status = ?"
        params.append(status)
    if min_fit_score is not None:
        query += " AND fit_score >= ?"
        params.append(min_fit_score)
    query += " ORDER BY fit_score DESC, created_at DESC"
    rows = conn.execute(query, params).fetchall()
    return [Lead(**dict(r)) for r in rows]
