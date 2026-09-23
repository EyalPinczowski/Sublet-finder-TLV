"""Tracks small scan-run bookkeeping timestamps — when the last scan
completed cleanly (`cli.py` uses this to compute a time-windowed cutoff:
first scan ever -> look back config.scan_window's initial_lookback_days;
every scan after that -> look back to the last successful scan instead)
and when dead-link pruning last ran (throttled to roughly once a day
rather than every scan — see cli._dead_link_prune_due). Deliberately a
small JSON file under data/ (mirrors llm_extractor.py's BUDGET_PATH), not
a store.py table — this is scan-run bookkeeping, not listing data, and
keeping it out of store.py guarantees zero interaction with the dedup
logic there.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "scan_state.json"


def _load_state() -> dict:
    try:
        with open(STATE_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_state(data: dict) -> None:
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _load_datetime(key: str) -> datetime | None:
    raw = _load_state().get(key)
    if not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def load_last_scan_completed_at() -> datetime | None:
    """None on a missing/corrupt file or key — treated as "no prior scan"
    (i.e. this is the first scan ever), same defensive load pattern as
    llm_extractor.py's _load_budget."""
    return _load_datetime("last_scan_completed_at")


def record_scan_completed(at: datetime | None = None) -> None:
    at = at or datetime.now(timezone.utc)
    data = _load_state()
    data["last_scan_completed_at"] = at.isoformat()
    _save_state(data)


def load_last_dead_link_prune_at() -> datetime | None:
    """None on a missing/corrupt file or key — treated as "never pruned
    before", same defensive load pattern as load_last_scan_completed_at."""
    return _load_datetime("last_dead_link_prune_at")


def record_dead_link_prune_completed(at: datetime | None = None) -> None:
    at = at or datetime.now(timezone.utc)
    data = _load_state()
    data["last_dead_link_prune_at"] = at.isoformat()
    _save_state(data)
