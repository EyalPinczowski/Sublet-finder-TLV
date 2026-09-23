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
