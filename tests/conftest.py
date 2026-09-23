import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from src import scan_state, store  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point src.store and src.scan_state at throwaway files for the
    duration of a test, so tests never touch data/listings.db or
    data/scan_state.json — the latter matters because _scan() reads/writes
    scan_state for both the cutoff watermark and the dead-link-prune
    throttle, and a test hitting the real file would both pollute it and
    behave non-deterministically depending on what a real scan last wrote
    there."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    monkeypatch.setattr(scan_state, "STATE_PATH", tmp_path / "scan_state.json")
    return path
