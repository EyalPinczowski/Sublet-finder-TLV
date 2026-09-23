from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import BrowserContext, sync_playwright

STORAGE_STATE_PATH = Path(__file__).resolve().parent.parent / "data" / "storage_state.json"

# A realistic desktop Chrome UA with no "HeadlessChrome" marker — Chromium's
# default headless UA advertises itself as headless, a giveaway to anti-bot
# checks. Only used for the headless (real-scan) path below; the headed
# login flow in login_and_save_session() is a real human in a real browser
# and needs no disguising.
_HEADLESS_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)


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
    # Anti-detection hardening, headless runs only — a real human drives the
    # headed login flow above, so it needs none of this.
    browser = playwright.chromium.launch(
        headless=headless,
        args=["--disable-blink-features=AutomationControlled"] if headless else [],
        ignore_default_args=["--enable-automation"] if headless else [],
    )
    context_kwargs: dict = {"storage_state": str(STORAGE_STATE_PATH)}
    if headless:
        context_kwargs["user_agent"] = _HEADLESS_USER_AGENT
    return browser.new_context(**context_kwargs)


@contextmanager
def open_scan_session(headless: bool = True):
    """One Playwright browser + authenticated context for an entire scan
    (every group, plus dead-link pruning) — opened once and reused rather
    than a fresh browser process per group/task. Cheaper, and reads as one
    continuous browsing session rather than a mechanically repeated
    launch/teardown pattern. Session cookies are re-saved to
    STORAGE_STATE_PATH on exit (best-effort) so Facebook's normal
    in-session cookie rotation is captured for next time, instead of every
    run replaying the exact same static cookie jar from the original
    manual login."""
    with sync_playwright() as p:
        context = open_authenticated_context(p, headless=headless)
        try:
            yield context
        finally:
            try:
                context.storage_state(path=str(STORAGE_STATE_PATH))
            except Exception:
                pass
            context.close()
