from unittest.mock import MagicMock, patch

from src import sheets
from src.listing_models import Listing


def _isolate(monkeypatch):
    monkeypatch.setattr(sheets, "_sheet", None)
    monkeypatch.setattr(sheets, "_checked", False)


def make_listing(**overrides) -> Listing:
    defaults = dict(
        post_url="https://facebook.com/groups/1/posts/1",
        group_name="Secret Tel Aviv",
        raw_text="raw",
        price=3300,
        rooms=3.0,
        address="דיזנגוף 120",
        score=80,
    )
    defaults.update(overrides)
    return Listing(**defaults)


def _fake_worksheet(existing_rows):
    ws = MagicMock()
    ws.get_all_values.return_value = existing_rows
    ws.col_values.return_value = [row[0] for row in existing_rows if row]
    ws.row_count = 1000
    return ws


def test_save_listing_noop_without_sheet_id(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.delenv("GOOGLE_SHEET_ID", raising=False)
    with patch("gspread.service_account") as mock_sa:
        sheets.save_listing(make_listing())
    mock_sa.assert_not_called()


def test_save_listing_noop_without_key_file(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    monkeypatch.setenv("GOOGLE_SHEET_ID", "some-id")
    monkeypatch.setattr(sheets, "SERVICE_ACCOUNT_PATH", tmp_path / "missing.json")
    with patch("gspread.service_account") as mock_sa:
        sheets.save_listing(make_listing())
    mock_sa.assert_not_called()


def test_writes_header_on_a_truly_blank_google_sheet(monkeypatch, tmp_path):
    # A brand-new Google Sheet returns a single row of blank-string cells
    # from get_all_values(), not [] — this is the exact shape that caused
    # the header-row check to be skipped in production.
    _isolate(monkeypatch)
    key_path = tmp_path / "key.json"
    key_path.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "some-id")
    monkeypatch.setattr(sheets, "SERVICE_ACCOUNT_PATH", key_path)

    ws = _fake_worksheet([[""]])
    client = MagicMock()
    client.open_by_key.return_value.sheet1 = ws
    with patch("gspread.service_account", return_value=client):
        sheets.save_listing(make_listing())

    header_call = ws.append_row.call_args_list[0]
    assert header_call.args[0] == sheets.HEADER


def test_skips_header_when_sheet_already_has_content(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    key_path = tmp_path / "key.json"
    key_path.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "some-id")
    monkeypatch.setattr(sheets, "SERVICE_ACCOUNT_PATH", key_path)

    ws = _fake_worksheet([sheets.HEADER])
    client = MagicMock()
    client.open_by_key.return_value.sheet1 = ws
    with patch("gspread.service_account", return_value=client):
        sheets.save_listing(make_listing())

    # Only the data row is appended — never a second header.
    appended = [call.args[0] for call in ws.append_row.call_args_list]
    assert sheets.HEADER not in appended


def test_skips_duplicate_post_url(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    key_path = tmp_path / "key.json"
    key_path.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "some-id")
    monkeypatch.setattr(sheets, "SERVICE_ACCOUNT_PATH", key_path)

    listing = make_listing()
    ws = _fake_worksheet([sheets.HEADER, [listing.post_url]])
    client = MagicMock()
    client.open_by_key.return_value.sheet1 = ws
    with patch("gspread.service_account", return_value=client):
        sheets.save_listing(listing)

    ws.append_row.assert_not_called()


def test_suitable_for_one_person():
    assert sheets._suitable_for(1) == "1 person"


def test_suitable_for_two_people():
    assert sheets._suitable_for(2) == "2 people"


def test_suitable_for_unknown_is_blank():
    assert sheets._suitable_for(None) == ""


def test_save_listing_writes_suitable_for_column(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    key_path = tmp_path / "key.json"
    key_path.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "some-id")
    monkeypatch.setattr(sheets, "SERVICE_ACCOUNT_PATH", key_path)

    ws = _fake_worksheet([sheets.HEADER])
    client = MagicMock()
    client.open_by_key.return_value.sheet1 = ws
    with patch("gspread.service_account", return_value=client):
        sheets.save_listing(make_listing(available_rooms=2))

    row = ws.append_row.call_args.args[0]
    assert row[sheets.HEADER.index("suitable_for")] == "2 people"


def test_price_cell_shows_not_listed_when_missing():
    assert sheets._price_cell(None) == "not listed"


def test_price_cell_shows_the_number_when_known():
    assert sheets._price_cell(3300) == 3300


def test_save_listing_writes_not_listed_for_missing_price(monkeypatch, tmp_path):
    _isolate(monkeypatch)
    key_path = tmp_path / "key.json"
    key_path.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "some-id")
    monkeypatch.setattr(sheets, "SERVICE_ACCOUNT_PATH", key_path)

    ws = _fake_worksheet([sheets.HEADER])
    client = MagicMock()
    client.open_by_key.return_value.sheet1 = ws
    with patch("gspread.service_account", return_value=client):
        sheets.save_listing(make_listing(price=None))

    row = ws.append_row.call_args.args[0]
    assert row[sheets.HEADER.index("price")] == "not listed"


def test_save_listing_writes_lease_start_and_stay_days(monkeypatch, tmp_path):
    from datetime import date

    _isolate(monkeypatch)
    key_path = tmp_path / "key.json"
    key_path.write_text("{}")
    monkeypatch.setenv("GOOGLE_SHEET_ID", "some-id")
    monkeypatch.setattr(sheets, "SERVICE_ACCOUNT_PATH", key_path)

    ws = _fake_worksheet([sheets.HEADER])
    client = MagicMock()
    client.open_by_key.return_value.sheet1 = ws
    listing = make_listing(lease_start_date=date(2026, 11, 1), lease_duration_days=14)
    with patch("gspread.service_account", return_value=client):
        sheets.save_listing(listing)

    row = ws.append_row.call_args.args[0]
    assert row[sheets.HEADER.index("lease_start")] == "2026-11-01"
    assert row[sheets.HEADER.index("stay_days")] == 14
