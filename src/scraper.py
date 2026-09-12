from __future__ import annotations

import time
from dataclasses import dataclass

from playwright.sync_api import Page, sync_playwright

from .browser import open_authenticated_context
from .config import FacebookGroup

# Facebook's markup uses randomized class names and changes often, so we lean
# on structural/ARIA hints (role="article") rather than CSS classes. This is
# best-effort scraping of a group you already belong to, using your own
# logged-in session — not mass harvesting. Expect to need small selector
# tweaks over time as Facebook's markup shifts.


@dataclass
class RawPost:
    post_url: str
    author: str
    text: str


def _scroll_to_load_posts(page: Page, target_count: int, max_scrolls: int = 15) -> None:
    for _ in range(max_scrolls):
        count = page.locator('[role="article"]').count()
        if count >= target_count:
            return
        page.mouse.wheel(0, 4000)
        time.sleep(2.0)


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
            # Skip posts we can't uniquely identify/dedupe.
            continue

        results.append(RawPost(post_url=post_url, author=author, text=text))
    return results


def scrape_group(group: FacebookGroup, limit: int, headless: bool = True) -> list[RawPost]:
    with sync_playwright() as p:
        context = open_authenticated_context(p, headless=headless)
        page = context.new_page()
        page.goto(group.url, wait_until="domcontentloaded")
        time.sleep(3.0)
        _scroll_to_load_posts(page, target_count=limit)
        posts = _extract_posts(page, limit=limit)
        context.close()
        return posts


def matches_keywords(text: str, keywords: list[str]) -> bool:
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in keywords)
