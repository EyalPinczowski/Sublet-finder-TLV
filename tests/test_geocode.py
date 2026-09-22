from unittest.mock import MagicMock, patch

from src import geocode


def _mock_response(payload):
    resp = MagicMock()
    resp.raise_for_status.return_value = None
    resp.json.return_value = payload
    return resp


def _isolate_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(geocode, "CACHE_PATH", tmp_path / "geocode_cache.json")
    monkeypatch.setattr(geocode, "_cache", None)
    monkeypatch.setattr(geocode, "_last_call", 0.0)


def test_geocode_returns_none_for_empty_address(tmp_path, monkeypatch):
    _isolate_cache(tmp_path, monkeypatch)
    assert geocode.geocode("") is None
    assert geocode.geocode(None) is None


def test_geocode_returns_coordinates_on_success(tmp_path, monkeypatch):
    _isolate_cache(tmp_path, monkeypatch)
    with patch(
        "src.geocode.requests.get",
        return_value=_mock_response([{"lat": "32.0768", "lon": "34.7742"}]),
    ):
        result = geocode.geocode("Dizengoff Square")
    assert result == (32.0768, 34.7742)


def test_geocode_returns_none_on_empty_results(tmp_path, monkeypatch):
    _isolate_cache(tmp_path, monkeypatch)
    with patch("src.geocode.requests.get", return_value=_mock_response([])):
        assert geocode.geocode("nowhere at all") is None


def test_geocode_returns_none_on_request_failure(tmp_path, monkeypatch):
    _isolate_cache(tmp_path, monkeypatch)
    with patch("src.geocode.requests.get", side_effect=Exception("network down")):
        assert geocode.geocode("Dizengoff Square") is None


def test_geocode_caches_and_does_not_re_request(tmp_path, monkeypatch):
    _isolate_cache(tmp_path, monkeypatch)
    with patch(
        "src.geocode.requests.get",
        return_value=_mock_response([{"lat": "32.0768", "lon": "34.7742"}]),
    ) as mock_get:
        geocode.geocode("Dizengoff Square")
        geocode.geocode("Dizengoff Square")
        geocode.geocode("dizengoff square")  # normalized the same
    assert mock_get.call_count == 1


def test_geocode_persists_cache_to_disk(tmp_path, monkeypatch):
    _isolate_cache(tmp_path, monkeypatch)
    with patch(
        "src.geocode.requests.get",
        return_value=_mock_response([{"lat": "32.0768", "lon": "34.7742"}]),
    ):
        geocode.geocode("Dizengoff Square")
    assert geocode.CACHE_PATH.exists()

    # A fresh in-memory cache should read the persisted result without a
    # network call.
    monkeypatch.setattr(geocode, "_cache", None)
    with patch("src.geocode.requests.get") as mock_get:
        result = geocode.geocode("Dizengoff Square")
    mock_get.assert_not_called()
    assert result == (32.0768, 34.7742)
