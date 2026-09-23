"""Tracks when the last scan completed cleanly, so `cli.py` can compute a
time-windowed cutoff (first scan ever -> look back config.scan_window's
initial_lookback_days; every scan after that -> look back to the last
successful scan instead). Deliberately a small JSON file under data/
(mirrors llm_extractor.py's BUDGET_PATH), not a store.py table — this is
scan-run bookkeeping, not listing data, and keeping it out of store.py
guarantees zero interaction with the dedup logic there.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "scan_state.json"


def load_last_scan_completed_at() -> datetime | None:
    """None on a missing/corrupt file — treated as "no prior scan" (i.e.
    this is the first scan ever), same defensive load pattern as
    llm_extractor.py's _load_budget."""
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    raw = data.get("last_scan_completed_at")
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def record_scan_completed(at: datetime | None = None) -> None:
    at = at or datetime.now(timezone.utc)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump({"last_scan_completed_at": at.isoformat()}, f)
