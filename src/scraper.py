from __future__ import annotations

import hashlib
import os
import random
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from .browser import open_authenticated_context
from .config import FacebookGroup

# Facebook's markup uses randomized class names and changes often, so we lean
# on structural/ARIA hints (role="article") rather than CSS classes. This is
# best-effort scraping of a group you already belong to, using your own
# logged-in session — not mass harvesting. Expect to need small selector
# tweaks over time as Facebook's markup shifts.

# Randomized delays instead of a fixed sleep, so scans don't look robotically
# periodic — the main thing that reads as automated to Facebook.
_SCROLL_DELAY = (1.5, 3.0)
_POST_LOAD_DELAY = (2.0, 4.5)
_GROUP_DELAY = (3.0, 7.0)


def _jitter(bounds: tuple[float, float]) -> None:
    time.sleep(random.uniform(*bounds))


@dataclass
class RawPost:
    post_url: str
    author: str
    text: str
    images: list[str] = field(default_factory=list)


class ScraperBlocked(Exception):
    """Facebook showed a checkpoint/login/verification wall instead of the
    group feed — never scrape this as if it were content."""


_BLOCK_URL_MARKERS = ("/checkpoint", "login.php", "/login/", "login/?")


def _blocked_reason(page: Page) -> str | None:
    """A human-readable reason if the page is a checkpoint/login wall, else
    None."""
    url = page.url
    if any(marker in url for marker in _BLOCK_URL_MARKERS):
        return f"redirected to a login/checkpoint page ({url})"
    try:
        if page.locator('input[name="email"]').count() and page.locator(
            'input[name="pass"]'
        ).count():
            return "a login form is showing instead of the group feed"
    except Exception:
        pass
    return None


def _text_sig(text: str) -> str:
    """A stable synthetic key for a post with no recoverable permalink
    (common for comment-less posts, which Facebook doesn't always expose a
    /posts/ or /permalink/ link for) — mirrors bgu-housing-bot's _text_sig.
    Used instead of dropping the post outright."""
    norm = re.sub(r"\s+", " ", text or "").strip()[:150]
    return "text:" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _images(article, limit: int = 6) -> list[str]:
    """Best-effort image URLs attached to a post, for sending as a Telegram
    photo/album. Bounded, and tolerant of a locator that finds nothing."""
    try:
        imgs = article.locator("img")
        n = min(imgs.count(), limit)
    except Exception:
        return []
    urls: list[str] = []
    for i in range(n):
        try:
            src = imgs.nth(i).get_attribute("src", timeout=500)
        except Exception:
            continue
        if src and src.startswith("http") and src not in urls:
            urls.append(src)
    return urls


def _scroll_to_load_posts(page: Page, target_count: int, max_scrolls: int = 15) -> None:
    for _ in range(max_scrolls):
        count = page.locator('[role="article"]').count()
        if count >= target_count:
            return
        page.mouse.wheel(0, 4000)
        _jitter(_SCROLL_DELAY)


def _extract_posts(page: Page, limit: int) -> list[RawPost]:
    articles = page.locator('[role="article"]')
    n = min(articles.count(), limit)
    results: list[RawPost] = []
    for i in range(n):
        article = articles.nth(i)
        try:
            text = article.inner_text(timeout=2000)
        except Exception:
            continue
        if not text.strip():
            continue

        author = ""
        try:
            # The author name is typically the first strong link in the post header.
            author = article.locator("h3 a, h2 a, strong a").first.inner_text(timeout=1000)
        except Exception:
            pass

        post_url = ""
        try:
            # Timestamp links are usually the permalink to the post.
            link = article.locator('a[href*="/posts/"], a[href*="/permalink/"]').first
            post_url = link.get_attribute("href", timeout=1000) or ""
        except Exception:
            pass

        if not post_url:
            # No recoverable permalink (common for comment-less posts) — use a
            # stable text-signature key instead of dropping the post, so it's
            # still captured and deduped rather than silently lost.
            post_url = _text_sig(text)

        results.append(
            RawPost(post_url=post_url, author=author, text=text, images=_images(article))
        )
    return results


def jitter_between_groups() -> None:
    """Called by the CLI between groups, so back-to-back group scans don't
    fire at a fixed, robotically periodic cadence."""
    _jitter(_GROUP_DELAY)


def scrape_group(group: FacebookGroup, limit: int, headless: bool = True) -> list[RawPost]:
    with sync_playwright() as p:
        context = open_authenticated_context(p, headless=headless)
        page = context.new_page()
        page.goto(group.url, wait_until="domcontentloaded")
        _jitter(_POST_LOAD_DELAY)
        reason = _blocked_reason(page)
        if reason:
            context.close()
            raise ScraperBlocked(f"{group.name}: {reason}")
        _scroll_to_load_posts(page, target_count=limit)
        posts = _extract_posts(page, limit=limit)
        context.close()
        return posts


# --- run lock: stop two scans from sharing the Playwright profile at once ---

LOCK_PATH = Path(__file__).resolve().parent.parent / "data" / "scan.lock"


class ScanAlreadyRunning(Exception):
    pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, just owned by someone else
    return True


@contextmanager
def run_lock():
    """Refuse to start a second concurrent scan — two Playwright instances
    sharing the same persistent Chromium profile can corrupt it. A lock file
    left behind by a process that's no longer running (crash, kill -9) is
    detected via a PID liveness check and reclaimed automatically."""
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    if LOCK_PATH.exists():
        try:
            pid = int(LOCK_PATH.read_text().strip())
        except ValueError:
            pid = None
        if pid is not None and _pid_alive(pid):
            raise ScanAlreadyRunning(f"a scan is already running (pid {pid})")
    LOCK_PATH.write_text(str(os.getpid()))
    try:
        yield
    finally:
        try:
            LOCK_PATH.unlink()
        except FileNotFoundError:
            pass
