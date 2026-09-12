from __future__ import annotations

from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

STORAGE_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "storage_state.json"


def login_and_save_session() -> None:
    """Open a real, visible browser so you can log into Facebook by hand.

    Facebook actively blocks headless/automated logins, so this always runs
    headed. Once you're logged in and can see your feed, come back to the
    terminal and press Enter — your session cookies get saved locally so
    future runs don't need you to log in again.
    """
    STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto("https://www.facebook.com/login")
        input(
            "\nLog into Facebook in the opened browser window, then press "
            "Enter here once you see your feed...\n"
        )
        context.storage_state(path=str(STORAGE_STATE_PATH))
        browser.close()
    print(f"Session saved to {STORAGE_STATE_PATH}")


def open_authenticated_context(playwright, headless: bool = True) -> BrowserContext:
    if not STORAGE_STATE_PATH.exists():
        raise RuntimeError(
            "No saved Facebook session found. Run `python -m src.cli login` first."
        )
    browser = playwright.chromium.launch(headless=headless)
    return browser.new_context(storage_state=str(STORAGE_STATE_PATH))
