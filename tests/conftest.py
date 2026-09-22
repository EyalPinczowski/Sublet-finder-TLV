import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from src import store  # noqa: E402


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Point src.store at a throwaway SQLite file for the duration of a
    test, so tests never touch data/listings.db."""
    path = tmp_path / "test.db"
    monkeypatch.setattr(store, "DB_PATH", path)
    return path
