from __future__ import annotations

import hashlib
import os
import random
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

from .browser import open_authenticated_context
from .config import FacebookGroup

# Facebook's markup uses randomized class names and changes often, so we lean
# on structural/ARIA hints (role="article") rather than CSS classes. This is
# best-effort scraping of a group you already belong to, using your own
# logged-in session — not mass harvesting. Expect to need small selector
# tweaks over time as Facebook's markup shifts.
#
# Post-timestamp extraction (_post_timestamp and friends below) and the
# "New posts" sort click (_force_chronological_sort) are UNVERIFIED against
# live Facebook markup — both were written from general knowledge of FB's
# structure, not a live authenticated page, and need one smoke-test pass
# before being trusted. Both fail safe: a timestamp that can't be parsed
# becomes "unknown age" (never dropped, never treated as old), and a sort
# click that fails just disables cutoff-based stopping for that scrape
# rather than under-scanning silently.

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
    posted_at: datetime | None = None  # None = unrecoverable, never "old"


class ScraperBlocked(Exception):
    """Facebook showed a checkpoint/login/verification wall instead of the
    group feed — never scrape this as if it were content."""


_BLOCK_URL_MARKERS = ("/checkpoint", "login.php", "/login/", "login/?")


def _save_checkpoint_snapshot(group_name: str, page: Page) -> None:
    """Best-effort debug screenshot when a checkpoint/login wall is hit
    during an unattended (headless) run, so a human can see what Facebook
    showed without needing to reproduce it — same idea as
    scripts/login_facebook_headless.py's save_debug_snapshot. Must be
    called before the context/page is closed."""
    safe_name = re.sub(r"[^\w\-]+", "_", group_name)
    path = Path(__file__).resolve().parent.parent / "data" / f"checkpoint_{safe_name}.png"
    try:
        page.screenshot(path=str(path), full_page=True)
    except Exception:
        pass


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


# --- post timestamp extraction (best-effort; see module docstring) ---

_UNIT_SECONDS = {"minutes": 60, "hours": 3600, "days": 86400, "weeks": 604800}

# (pattern, unit, amount-to-use-when-no-digit-was-captured)
_RELATIVE_PATTERNS: list[tuple[re.Pattern, str, int]] = [
    (re.compile(r"עכשיו|הרגע"), "minutes", 0),
    (re.compile(r"\bjust now\b", re.IGNORECASE), "minutes", 0),
    (re.compile(r"אתמול"), "days", 1),
    (re.compile(r"\byesterday\b", re.IGNORECASE), "days", 1),
    (re.compile(r"לפני\s+דקה\b"), "minutes", 1),
    (re.compile(r"לפני\s+שעה\b"), "hours", 1),
    (re.compile(r"לפני\s+יום\b"), "days", 1),
    (re.compile(r"לפני\s+שבוע\b"), "weeks", 1),
    (re.compile(r"לפני\s+(\d+)\s+דקות"), "minutes", 0),
    (re.compile(r"לפני\s+(\d+)\s+שעות"), "hours", 0),
    (re.compile(r"לפני\s+(\d+)\s+ימים"), "days", 0),
    (re.compile(r"לפני\s+(\d+)\s+שבועות"), "weeks", 0),
    (re.compile(r"\ban?\s+minute\b", re.IGNORECASE), "minutes", 1),
    (re.compile(r"\ban?\s+hour\b", re.IGNORECASE), "hours", 1),
    (re.compile(r"(\d+)\s*(?:m|mins?|minutes?)\b", re.IGNORECASE), "minutes", 0),
    (re.compile(r"(\d+)\s*(?:h|hrs?|hours?)\b", re.IGNORECASE), "hours", 0),
    (re.compile(r"(\d+)\s*(?:d|days?)\b", re.IGNORECASE), "days", 0),
    (re.compile(r"(\d+)\s*(?:w|weeks?)\b", re.IGNORECASE), "weeks", 0),
]

_ABSOLUTE_TIMESTAMP_FORMATS = [
    "%A, %B %d, %Y at %I:%M %p",
    "%B %d, %Y at %I:%M %p",
    "%b %d, %Y at %I:%M %p",
    "%B %d, %Y",
    "%b %d, %Y",
]


def _parse_relative_timestamp(text: str, now: datetime | None = None) -> datetime | None:
    """Best-effort parse of Facebook's relative post-time text ("2 hrs",
    "לפני 3 שעות", "Yesterday", "אתמול", ...) into an absolute UTC datetime.
    Returns None — never a guess — when nothing matches; callers must treat
    that as "unknown age", never as "old"."""
    if not text:
        return None
    now = now or datetime.now(timezone.utc)
    stripped = text.strip()
    for pattern, unit, default_amount in _RELATIVE_PATTERNS:
        match = pattern.search(stripped)
        if not match:
            continue
        digit_groups = [g for g in match.groups() if g and g.isdigit()]
        amount = int(digit_groups[0]) if digit_groups else default_amount
        return now - timedelta(seconds=amount * _UNIT_SECONDS[unit])
    return None


def _parse_absolute_timestamp(raw: str) -> datetime | None:
    """Best-effort parse of an absolute datetime string Facebook sometimes
    exposes via a title/aria-label attribute on the post-time element (the
    exact format is unverified against live markup — see module docstring).
    Tries ISO-8601 first, then a handful of common English long-form
    patterns, and gives up cleanly (None) rather than guessing."""
    if not raw:
        return None
    raw = raw.strip()
    try:
        iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(iso)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        pass
    for fmt in _ABSOLUTE_TIMESTAMP_FORMATS:
        try:
            dt = datetime.strptime(raw, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _post_timestamp(article) -> datetime | None:
    """Best-effort post time: tries an absolute machine-readable attribute
    first (title/aria-label on the post's time element), then falls back to
    parsing that same element's visible relative-time text. Returns None —
    never a guess — when neither works; callers must treat that as "unknown
    age", never as "old enough to stop"."""
    try:
        time_el = article.locator(
            "a[href*='/posts/'] abbr, a[href*='/posts/'] span, [role='link'] abbr"
        ).first
        raw_attr = time_el.get_attribute("title", timeout=500) or time_el.get_attribute(
            "aria-label", timeout=500
        )
    except Exception:
        return None
    if raw_attr:
        dt = _parse_absolute_timestamp(raw_attr)
        if dt:
            return dt
    try:
        text = time_el.inner_text(timeout=500)
    except Exception:
        return None
    return _parse_relative_timestamp(text)


def _force_chronological_sort(page: Page) -> bool:
    """Switches the group feed's sort from Facebook's default "Most
    relevant" to "New posts" — required for cutoff-based scroll-stopping to
    be valid at all (if the feed isn't chronological, stopping once "old"
    posts are seen could skip newer ones further down). Best-effort: if the
    sort control can't be found/clicked, returns False so the caller can
    fall back to non-cutoff (pure count) scrolling rather than silently
    under-scan."""
    try:
        page.get_by_role("button", name=re.compile("Sort|מיון")).first.click(timeout=2000)
        page.get_by_text(re.compile("New posts|החדשים ביותר|החדשות ביותר")).first.click(
            timeout=2000
        )
        _jitter(_SCROLL_DELAY)
        return True
    except Exception:
        return False


_CONSECUTIVE_OLD_TO_STOP = 3  # tolerate a stray out-of-order/pinned post


def _extract_one_post(article) -> RawPost | None:
    try:
        text = article.inner_text(timeout=2000)
    except Exception:
        return None
    if not text.strip():
        return None

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

    return RawPost(
        post_url=post_url,
        author=author,
        text=text,
        images=_images(article),
        posted_at=_post_timestamp(article),
    )


def _scroll_and_extract(
    page: Page, limit: int, cutoff: datetime | None, max_scrolls: int = 15
) -> list[RawPost]:
    """Scrolls and extracts together (rather than scroll-then-extract) so
    the cutoff-stop decision can see timestamps as they're discovered.
    Stops on whichever comes first: `limit` posts extracted (hard safety
    cap), `_CONSECUTIVE_OLD_TO_STOP` consecutive posts strictly older than
    `cutoff` in a row (tolerates a stray out-of-order/pinned post), or
    `max_scrolls` reached. `cutoff=None` disables age-based stopping
    entirely (pure count-based legacy behavior). A post with
    posted_at=None (unparseable timestamp) never counts toward the
    consecutive-old counter and is never itself a stop reason — unknown
    age means "keep going", never "old enough to stop"."""
    seen_urls: set[str] = set()
    results: list[RawPost] = []
    examined = 0  # DOM articles already turned into a result-or-skip
    consecutive_old = 0
    for _ in range(max_scrolls):
        articles = page.locator('[role="article"]')
        count = articles.count()
        for i in range(examined, min(count, limit)):
            examined = i + 1
            post = _extract_one_post(articles.nth(i))
            if post is None or post.post_url in seen_urls:
                continue
            seen_urls.add(post.post_url)
            results.append(post)
            if cutoff is not None and post.posted_at is not None:
                if post.posted_at < cutoff:
                    consecutive_old += 1
                    if consecutive_old >= _CONSECUTIVE_OLD_TO_STOP:
                        return results
                else:
                    consecutive_old = 0
        if len(results) >= limit:
            return results
        page.mouse.wheel(0, random.randint(2500, 4500))
        _jitter(_SCROLL_DELAY)
    return results


def jitter_between_groups() -> None:
    """Called by the CLI between groups, so back-to-back group scans don't
    fire at a fixed, robotically periodic cadence."""
    _jitter(_GROUP_DELAY)


def scrape_group(
    group: FacebookGroup, limit: int, cutoff: datetime | None = None, headless: bool = True
) -> list[RawPost]:
    with sync_playwright() as p:
        context = open_authenticated_context(p, headless=headless)
        page = context.new_page()
        page.goto(group.url, wait_until="domcontentloaded")
        _jitter(_POST_LOAD_DELAY)
        reason = _blocked_reason(page)
        if reason:
            _save_checkpoint_snapshot(group.name, page)
            context.close()
            raise ScraperBlocked(f"{group.name}: {reason}")
        sorted_chronologically = _force_chronological_sort(page)
        effective_cutoff = cutoff if sorted_chronologically else None
        posts = _scroll_and_extract(page, limit=limit, cutoff=effective_cutoff)
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
