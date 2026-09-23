from unittest.mock import MagicMock, patch

from src import browser


def test_open_scan_session_saves_cookies_before_closing(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "STORAGE_STATE_PATH", tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").write_text("{}")  # open_authenticated_context requires it

    mock_context = MagicMock()
    call_order = []
    mock_context.storage_state.side_effect = lambda **_: call_order.append("storage_state")
    mock_context.close.side_effect = lambda: call_order.append("close")

    with patch("src.browser.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.return_value.__enter__.return_value = MagicMock()
        with patch("src.browser.open_authenticated_context", return_value=mock_context):
            with browser.open_scan_session(headless=True) as context:
                assert context is mock_context

    assert call_order == ["storage_state", "close"]


def test_open_scan_session_still_closes_context_if_body_raises(tmp_path, monkeypatch):
    monkeypatch.setattr(browser, "STORAGE_STATE_PATH", tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").write_text("{}")

    mock_context = MagicMock()

    with patch("src.browser.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.return_value.__enter__.return_value = MagicMock()
        with patch("src.browser.open_authenticated_context", return_value=mock_context):
            try:
                with browser.open_scan_session(headless=True):
                    raise ValueError("boom")
            except ValueError:
                pass

    mock_context.storage_state.assert_called_once()
    mock_context.close.assert_called_once()


def test_open_scan_session_survives_storage_state_failure(tmp_path, monkeypatch):
    """A failure re-saving cookies must never prevent context.close() or
    mask the real exception from the scan itself."""
    monkeypatch.setattr(browser, "STORAGE_STATE_PATH", tmp_path / "storage_state.json")
    (tmp_path / "storage_state.json").write_text("{}")

    mock_context = MagicMock()
    mock_context.storage_state.side_effect = Exception("disk full")

    with patch("src.browser.sync_playwright") as mock_sync_playwright:
        mock_sync_playwright.return_value.__enter__.return_value = MagicMock()
        with patch("src.browser.open_authenticated_context", return_value=mock_context):
            with browser.open_scan_session(headless=True):
                pass

    mock_context.close.assert_called_once()
