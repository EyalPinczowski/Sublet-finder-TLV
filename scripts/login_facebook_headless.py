#!/usr/bin/env python3
"""Log into Facebook headlessly using your email/password from the terminal.

No browser window or remote view needed. Your password is typed directly
into Facebook's real login page by a local, headless browser — it is never
shown, logged, or written to disk, and never leaves this device.

If Facebook challenges the login with a one-time code, you'll be prompted
for it here. If it instead asks you to approve from your phone's Facebook
app, just approve it there — this script keeps waiting either way.

Usage: python scripts/login_facebook_headless.py
"""
import getpass
import sys
import time

import _bootstrap  # noqa: F401
from playwright.sync_api import Page, sync_playwright

from src.browser import STORAGE_STATE_PATH

CHALLENGE_TIMEOUT_SECONDS = 240
REALISTIC_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
)
EMAIL_INPUT_SELECTORS = ['#email', 'input[name="email"]']
PASSWORD_INPUT_SELECTORS = ['#pass', 'input[name="pass"]']
COOKIE_CONSENT_SELECTORS = [
    'button[data-cookiebanner="accept_button"]',
    'button:has-text("Allow all cookies")',
    'button:has-text("Allow essential and optional cookies")',
    'button:has-text("Decline optional cookies")',
]
CODE_INPUT_SELECTORS = [
    'input[name="approvals_code"]',
    'input[autocomplete="one-time-code"]',
    'input[aria-label="Code"]',
]
SUBMIT_SELECTORS = [
    'input[type="submit"]',
    'button[name="login"]',
    "#loginbutton",
    'button[type="submit"]',
    '[role="button"][aria-label="Log In"]',
    'div[aria-label="Continue"]',
]


def is_logged_in(page: Page) -> bool:
    return any(c["name"] == "c_user" for c in page.context.cookies("https://www.facebook.com"))


def try_click(page: Page, selectors: list[str]) -> bool:
    for sel in selectors:
        loc = page.locator(sel).first
        if loc.count() > 0:
            try:
                loc.click(timeout=2000)
                return True
            except Exception:
                continue
    return False


def click_login_button(page: Page) -> bool:
    # Facebook's real "Log in" control is a JS-driven role="button" element;
    # the underlying <input type="submit"> exists but is visually hidden and
    # isn't wired to the click handler, so it must be clicked by accessible
    # role/name rather than a plain CSS selector.
    by_role = page.get_by_role("button", name="Log in")
    if by_role.count() > 0:
        try:
            by_role.click(timeout=5000)
            return True
        except Exception:
            pass
    return try_click(page, SUBMIT_SELECTORS)


def find_login_error(page: Page) -> str | None:
    alert = page.locator('[role="alert"]').first
    if alert.count() > 0:
        text = alert.inner_text().strip()
        if text:
            return text
    return None


def find_code_input(page: Page):
    for sel in CODE_INPUT_SELECTORS:
        loc = page.locator(sel).first
        if loc.count() > 0:
            return loc
    return None


def save_debug_snapshot(page: Page) -> None:
    shot_path = STORAGE_STATE_PATH.parent / "login_debug.png"
    html_path = STORAGE_STATE_PATH.parent / "login_debug.html"
    try:
        page.screenshot(path=str(shot_path), full_page=True)
        html_path.write_text(page.content(), encoding="utf-8")
        print(f"Saved a screenshot to {shot_path} and the page HTML to {html_path}.")
    except Exception:
        pass


def find_first(page: Page, selectors: list[str]):
    for sel in selectors:
        loc = page.locator(sel).first
        if loc.count() > 0:
            return loc
    return None


def main() -> int:
    STORAGE_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    email = input("Facebook email/phone: ").strip()
    password = getpass.getpass("Facebook password (hidden): ")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent=REALISTIC_USER_AGENT,
            viewport={"width": 1280, "height": 800},
            locale="en-US",
        )
        page = context.new_page()
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
        page.wait_for_timeout(2000)
        try_click(page, COOKIE_CONSENT_SELECTORS)

        email_input = find_first(page, EMAIL_INPUT_SELECTORS)
        if email_input is None:
            print(
                "Could not find the email field — Facebook served something other "
                "than the normal login form (regional variant, consent wall, or a "
                "page aimed at automated browsers)."
            )
            print(f"Current URL: {page.url}")
            print(f"Page title: {page.title()}")
            save_debug_snapshot(page)
            browser.close()
            return 1

        email_input.fill(email)
        password_input = find_first(page, PASSWORD_INPUT_SELECTORS)
        if password_input is None:
            print("Could not find the password field.")
            save_debug_snapshot(page)
            browser.close()
            return 1
        password_input.fill(password)
        del password  # don't keep it around any longer than needed
        click_login_button(page)
        page.wait_for_timeout(3000)

        if is_logged_in(page):
            context.storage_state(path=str(STORAGE_STATE_PATH))
            print(f"LOGIN_SUCCESS saved to {STORAGE_STATE_PATH}")
            browser.close()
            return 0

        error = find_login_error(page)
        if error:
            print(f"Facebook rejected the login: {error}")
            browser.close()
            return 1

        # Handle a one-time-code challenge, or wait out an app-approval challenge.
        code_input = find_code_input(page)
        if code_input is not None:
            code = input("Facebook is asking for a verification code. Enter it: ").strip()
            code_input.fill(code)
            continue_btn = page.get_by_role("button", name="Continue")
            if continue_btn.count() > 0:
                continue_btn.click(timeout=5000)
            else:
                try_click(page, SUBMIT_SELECTORS)
            page.wait_for_timeout(3000)
        else:
            print(
                "Facebook may be asking you to approve this login from your phone's "
                "Facebook app — check it now. Waiting..."
            )

        deadline = time.time() + CHALLENGE_TIMEOUT_SECONDS
        while time.time() < deadline:
            if is_logged_in(page):
                context.storage_state(path=str(STORAGE_STATE_PATH))
                print(f"LOGIN_SUCCESS saved to {STORAGE_STATE_PATH}")
                browser.close()
                return 0
            time.sleep(3)

        print(f"Still not logged in. Current URL: {page.url}")
        print(f"Page title: {page.title()}")
        save_debug_snapshot(page)
        browser.close()
        return 1


if __name__ == "__main__":
    sys.exit(main())
