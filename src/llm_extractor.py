"""LLM extraction of a Hebrew/English sublet post -> Listing, via the
Gemini free tier.

Adapted from bgu-housing-bot's llm.py, trimmed to what this tool actually
searches for: a whole-apartment sublet price (not BGU's per-room figure, so
none of its price-division recovery logic applies), no floor/furnished/
balcony/elevator fields (this tool doesn't score on them).

This is the PRIMARY extraction path when GEMINI_API_KEY is set; callers
must fall back to listing_parser.parse_listing when extract() returns None
(no key, budget exhausted, or the call failed) — see cli.cmd_scan.
"""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path
from typing import Optional

from pydantic import BaseModel

from .config import LLMConfig
from .listing_models import Listing
from .listing_parser import _matched_neighborhoods

BUDGET_PATH = Path(__file__).resolve().parent.parent / "data" / "llm_budget.json"

# Hebrew+English instruction prompt. The null-not-guess rule is the single
# most important line — a hallucinated price would sail through the price
# filter.
_SYSTEM_PROMPT = """אתה מנתח מודעות סאבלט/שכירות דירות בתל אביב, מקבוצות פייסבוק בעברית ואנגלית.
חלץ את השדות לפי הסכימה. כללים מחייבים:
- אם שדה כלשהו אינו מופיע במפורש במודעה — החזר null. אסור לנחש או להמציא מספרים.
- is_offer = true רק אם הפוסט *מציע* דירה/חדר/סאבלט להשכרה. false אם מדובר במישהו
  שמחפש דירה/חדר לעצמו ("מחפש/ת דירה"), או בפוסט שאינו קשור לשכירות דירות כלל.
- price_ils = שכר הדירה החודשי הכולל (לא לחדר/לאדם) בשקלים. אם לא צוין — null.
- rooms = מספר החדרים הכולל בדירה (הגודל הכולל של הדירה, לא כמה פנויים).
- available_rooms = כמה חדרים/מקומות פנויים להשכרה *כרגע* מוצעים בפוסט הזה —
  שונה מ-rooms! לדוגמה: "מתפנה חדר בדירת 3 חדרים" -> available_rooms=1,
  rooms=3. "שני חדרים פנויים בדירה משותפת" -> available_rooms=2. אם לא ניתן
  לקבוע כמה פנויים — null.
- address = הכתובת או האזור המדויקים ביותר כפי שמופיעים במודעה (רחוב ומספר בית אם
  יש, או שם שכונה/אזור מדובר). null אם אין שום אזכור מיקום.
- roommates = מספר השותפים הכולל בדירה (כולל השוכר החדש).
- toilets = מספר חדרי השירותים/אמבטיות.
- separate_toilet_shower = true אם מצוין שהשירותים נפרדים מהמקלחת.
- contact_phone = מספר טלפון או קישור וואטסאפ ליצירת קשר, אם מופיע.
- lease_start_date = מתי ניתן להיכנס לדירה, כתאריך בפורמט YYYY-MM-DD. חשב
  תאריכים יחסיים ("מיידי", "מחר", "מ-1.11" ללא שנה) לפי התאריך של היום
  שניתן לך למטה. אם לא מוזכר תאריך כניסה כלל — null.
- lease_end_date = תאריך היציאה/סיום השכירות, YYYY-MM-DD, רק אם מוזכר
  תאריך סיום מפורש (למשל "עד 20.12" או "מ-1.11 עד 20.11"). אחרת null.
- lease_duration_days = משך השכירות בימים, רק אם מוזכרת תקופה מפורשת
  במילים ("שבועיים", "לחודש", "ל-10 ימים") ואין תאריך סיום מפורש (אם יש גם
  תאריך סיום וגם תיאור תקופה, החזר את lease_end_date ואת lease_duration_days
  כ-null — החישוב ייעשה מהתאריכים). אחרת null.
- summary = משפט תקציר קצר אחד באנגלית או עברית.
החזר JSON בלבד."""


class ListingExtract(BaseModel):
    is_offer: bool
    price_ils: Optional[int] = None
    rooms: Optional[float] = None
    available_rooms: Optional[int] = None
    address: Optional[str] = None
    roommates: Optional[int] = None
    toilets: Optional[int] = None
    separate_toilet_shower: Optional[bool] = None
    contact_phone: Optional[str] = None
    lease_start_date: Optional[str] = None  # ISO YYYY-MM-DD
    lease_end_date: Optional[str] = None  # ISO YYYY-MM-DD
    lease_duration_days: Optional[int] = None
    summary: Optional[str] = None


class LLMUnavailable(Exception):
    """Raised by extract() when the caller should fall back to
    listing_parser.parse_listing instead — the key is unset, today's budget
    is spent, or the call itself failed. Distinct from a normal "the LLM
    looked at this and it's not an offer" result (which returns None), so a
    confident classification is never second-guessed by the weaker regex
    fallback."""


_last_call = 0.0


def _today() -> str:
    return date.today().isoformat()


def _load_budget() -> dict:
    try:
        with open(BUDGET_PATH, encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"date": _today(), "count": 0}
    if data.get("date") != _today():
        return {"date": _today(), "count": 0}
    return data


def _spend_budget() -> None:
    data = _load_budget()
    data["count"] += 1
    BUDGET_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(BUDGET_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f)


def _budget_remaining(config: LLMConfig) -> int:
    if config.daily_budget <= 0:
        return 1  # 0 = no ceiling (still gated by api_key being set)
    return config.daily_budget - _load_budget()["count"]


def _pace(config: LLMConfig) -> None:
    global _last_call
    gap = config.min_interval_seconds - (time.monotonic() - _last_call)
    if gap > 0:
        time.sleep(gap)
    _last_call = time.monotonic()
    _spend_budget()


def _extract_gemini(text: str, config: LLMConfig) -> ListingExtract:
    from google import genai

    _pace(config)
    client = genai.Client(api_key=config.api_key)
    resp = client.models.generate_content(
        model="gemini-flash-lite-latest",
        contents=[
            _SYSTEM_PROMPT,
            f"\n\nהיום התאריך {_today()}.",
            "\n\nהפוסט:\n" + text,
        ],
        config={
            "response_mime_type": "application/json",
            "response_schema": ListingExtract,
        },
    )
    return ListingExtract.model_validate_json(resp.text)


def _parse_date(value: Optional[str]):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None  # the model returned something malformed — don't guess


def extract(
    text: str,
    post_url: str,
    group_name: str,
    config: LLMConfig,
    known_neighborhoods: Optional[list[str]] = None,
    images: Optional[list[str]] = None,
) -> Optional[Listing]:
    """A Listing built from a Gemini extraction, or None when the LLM
    confidently classified this post as not a sublet offer (a real verdict,
    not a fallback signal — the caller should drop the post, not hand it to
    the regex parser). Raises LLMUnavailable when the caller should fall
    back to listing_parser.parse_listing instead: the key is unset, today's
    budget is spent, or the call itself failed."""
    if not config.active:
        raise LLMUnavailable("no GEMINI_API_KEY configured")
    if _budget_remaining(config) <= 0:
        raise LLMUnavailable("daily budget spent")
    try:
        e = _extract_gemini(text, config)
    except Exception as exc:
        raise LLMUnavailable(str(exc)) from exc
    if not e.is_offer:
        return None
    return Listing(
        post_url=post_url,
        group_name=group_name,
        raw_text=text,
        price=e.price_ils,
        rooms=e.rooms,
        available_rooms=e.available_rooms,
        neighborhoods_mentioned=_matched_neighborhoods(text, known_neighborhoods or []),
        roommates=e.roommates,
        toilets=e.toilets,
        separate_toilet_shower=bool(e.separate_toilet_shower),
        address=e.address,
        phone=e.contact_phone,
        images=images or [],
        summary=e.summary,
        lease_start_date=_parse_date(e.lease_start_date),
        lease_end_date=_parse_date(e.lease_end_date),
        lease_duration_days=e.lease_duration_days,
    )
