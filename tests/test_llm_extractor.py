from datetime import date
from unittest.mock import patch

import pytest

from src import llm_extractor
from src.config import LLMConfig
from src.llm_extractor import ListingExtract, LLMUnavailable, _parse_date, extract


def _isolate_budget(tmp_path, monkeypatch):
    monkeypatch.setattr(llm_extractor, "BUDGET_PATH", tmp_path / "llm_budget.json")
    monkeypatch.setattr(llm_extractor, "_last_call", 0.0)


def test_extract_raises_unavailable_without_api_key(tmp_path, monkeypatch):
    _isolate_budget(tmp_path, monkeypatch)
    config = LLMConfig(enabled=True, api_key=None)
    with pytest.raises(LLMUnavailable):
        extract("some post", "https://facebook.com/x", "group", config)


def test_extract_raises_unavailable_when_disabled(tmp_path, monkeypatch):
    _isolate_budget(tmp_path, monkeypatch)
    config = LLMConfig(enabled=False, api_key="fake-key")
    with pytest.raises(LLMUnavailable):
        extract("some post", "https://facebook.com/x", "group", config)


def test_extract_raises_unavailable_when_budget_spent(tmp_path, monkeypatch):
    _isolate_budget(tmp_path, monkeypatch)
    config = LLMConfig(enabled=True, api_key="fake-key", daily_budget=1)
    llm_extractor.BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    llm_extractor.BUDGET_PATH.write_text(
        '{"date": "' + llm_extractor._today() + '", "count": 1}'
    )
    with pytest.raises(LLMUnavailable):
        extract("some post", "https://facebook.com/x", "group", config)


def test_extract_raises_unavailable_when_call_fails(tmp_path, monkeypatch):
    _isolate_budget(tmp_path, monkeypatch)
    config = LLMConfig(enabled=True, api_key="fake-key")
    with patch("src.llm_extractor._extract_gemini", side_effect=Exception("boom")):
        with pytest.raises(LLMUnavailable):
            extract("some post", "https://facebook.com/x", "group", config)


def test_extract_returns_none_for_non_offer(tmp_path, monkeypatch):
    _isolate_budget(tmp_path, monkeypatch)
    config = LLMConfig(enabled=True, api_key="fake-key")
    with patch(
        "src.llm_extractor._extract_gemini",
        return_value=ListingExtract(is_offer=False),
    ):
        assert extract("some post", "https://facebook.com/x", "group", config) is None


def test_extract_builds_listing_from_offer(tmp_path, monkeypatch):
    _isolate_budget(tmp_path, monkeypatch)
    config = LLMConfig(enabled=True, api_key="fake-key")
    parsed = ListingExtract(
        is_offer=True,
        price_ils=3300,
        rooms=3.0,
        available_rooms=2,
        address="דיזנגוף 120",
        roommates=2,
        toilets=2,
        separate_toilet_shower=True,
        contact_phone="050-1234567",
        lease_start_date="2026-11-01",
        lease_end_date="2026-11-20",
        summary="Nice place near Dizengoff",
    )
    with patch("src.llm_extractor._extract_gemini", return_value=parsed):
        listing = extract(
            "some post",
            "https://facebook.com/x",
            "group",
            config,
            known_neighborhoods=["florentin"],
            images=["https://example.com/a.jpg"],
        )
    assert listing is not None
    assert listing.price == 3300
    assert listing.rooms == 3.0
    assert listing.available_rooms == 2
    assert listing.address == "דיזנגוף 120"
    assert listing.phone == "050-1234567"
    assert listing.images == ["https://example.com/a.jpg"]
    assert listing.summary == "Nice place near Dizengoff"
    assert listing.lease_start_date == date(2026, 11, 1)
    assert listing.lease_end_date == date(2026, 11, 20)


def test_extract_passes_through_explicit_duration(tmp_path, monkeypatch):
    _isolate_budget(tmp_path, monkeypatch)
    config = LLMConfig(enabled=True, api_key="fake-key")
    parsed = ListingExtract(is_offer=True, lease_duration_days=14)
    with patch("src.llm_extractor._extract_gemini", return_value=parsed):
        listing = extract("some post", "https://facebook.com/x", "group", config)
    assert listing.lease_duration_days == 14
    assert listing.lease_start_date is None


def test_parse_date_handles_valid_iso_string():
    assert _parse_date("2026-11-01") == date(2026, 11, 1)


def test_parse_date_returns_none_for_missing_or_malformed():
    assert _parse_date(None) is None
    assert _parse_date("") is None
    assert _parse_date("not-a-date") is None
