from datetime import datetime, timezone

from src import scan_state


def test_load_returns_none_when_file_missing(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_state, "STATE_PATH", tmp_path / "scan_state.json")
    assert scan_state.load_last_scan_completed_at() is None


def test_load_returns_none_on_corrupt_json(tmp_path, monkeypatch):
    path = tmp_path / "scan_state.json"
    path.write_text("{not valid json")
    monkeypatch.setattr(scan_state, "STATE_PATH", path)
    assert scan_state.load_last_scan_completed_at() is None


def test_load_returns_none_when_field_missing(tmp_path, monkeypatch):
    path = tmp_path / "scan_state.json"
    path.write_text("{}")
    monkeypatch.setattr(scan_state, "STATE_PATH", path)
    assert scan_state.load_last_scan_completed_at() is None


def test_record_then_load_round_trips(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_state, "STATE_PATH", tmp_path / "scan_state.json")
    at = datetime(2026, 9, 23, 8, 0, 0, tzinfo=timezone.utc)
    scan_state.record_scan_completed(at)
    assert scan_state.load_last_scan_completed_at() == at


def test_record_defaults_to_now(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_state, "STATE_PATH", tmp_path / "scan_state.json")
    before = datetime.now(timezone.utc)
    scan_state.record_scan_completed()
    after = datetime.now(timezone.utc)
    loaded = scan_state.load_last_scan_completed_at()
    assert before <= loaded <= after


def test_dead_link_prune_round_trips_independently_of_scan_completed(tmp_path, monkeypatch):
    """The two timestamps share one JSON file — recording one must not
    clobber the other."""
    monkeypatch.setattr(scan_state, "STATE_PATH", tmp_path / "scan_state.json")
    scan_at = datetime(2026, 9, 23, 8, 0, 0, tzinfo=timezone.utc)
    prune_at = datetime(2026, 9, 22, 6, 0, 0, tzinfo=timezone.utc)
    scan_state.record_scan_completed(scan_at)
    scan_state.record_dead_link_prune_completed(prune_at)
    assert scan_state.load_last_scan_completed_at() == scan_at
    assert scan_state.load_last_dead_link_prune_at() == prune_at


def test_load_last_dead_link_prune_at_none_when_never_recorded(tmp_path, monkeypatch):
    monkeypatch.setattr(scan_state, "STATE_PATH", tmp_path / "scan_state.json")
    assert scan_state.load_last_dead_link_prune_at() is None
