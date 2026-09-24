from __future__ import annotations

import re
from datetime import date

from .listing_models import Listing

OFFER_KEYWORDS = [
    "סאבלט",
    "סבלט",
    "sublet",
    "subletting",
    "להשכרה לתקופה",
    "להשכרה זמנית",
]

# Posts asking for a place rather than offering one — dropped even when they
# also mention "sublet", since "מחפש/ת סאבלט" means "looking for a sublet".
SEEKER_KEYWORDS = [
    "מחפש",
    "מחפשת",
    "מחפשים",
    "looking for",
    "searching for",
]

# Comma/period-grouped thousands (e.g. "4,500") or a plain digit run (e.g.
# "3000"); the lookaround guards stop either alternative from matching a
# partial substring of a longer number. Reused across all three
# alternatives below via the same capture-group shape.
_PRICE_NUMBER = r'(?<!\d)(\d{1,3}(?:[,.]\d{3})+|\d{2,6})(?!\d)'
# Three ways a price shows up: a currency marker right after the number
# (the original, tightest case), a "per month" phrase right after it with
# no currency word at all ("4000 לחודש"), or a "price:"-style label right
# before it ("מחיר: 4000"). Each stays tightly anchored (no free-floating
# unqualified number) to avoid matching a phone number, room count, or
# address digit that happens to be nearby.
PRICE_RE = re.compile(
    _PRICE_NUMBER + r'\s*(?:₪|ש"ח|שקל|nis)'
    r"|" + _PRICE_NUMBER + r"\s*/?\s*(?:לחודש|בחודש|חודשי|per\s*month|a\s*month|monthly)"
    r"|(?:מחיר|price)\s*[:\-]?\s*" + _PRICE_NUMBER +
    # An explicit "total for the whole period" phrase ("2,500 לכל
    # התקופה", "2500 סה״כ") — common for short-term sublets, and already
    # the right number as-is under this project's price convention (the
    # TOTAL for the stay), unlike the per-week/per-day rates above.
    r'|' + _PRICE_NUMBER + r'\s*(?:₪|ש"ח|שקל)?\s*'
    r'(?:לכל\s*התקופה|לתקופה|סה"?כ|סך\s*הכל|total)',
    re.IGNORECASE,
)
# A per-week/per-day RATE ("1000 ש"ח לשבוע", "150 ליום") is a different
# number than this project's price convention (see
# listing_filters.matches_without_location's proration comment): a
# short-stay listing's price is treated as the TOTAL for its whole
# stated period, not a per-unit rate. Checked BEFORE PRICE_RE, since
# "1000 ש"ח" in "1000 ש"ח לשבוע" would otherwise match PRICE_RE's plain
# currency-marker branch too and silently keep the bare weekly/daily
# number as if it were the stay's total cost.
_PRICE_PER_WEEK_RE = re.compile(
    _PRICE_NUMBER + r'\s*(?:₪|ש"ח|שקל|nis)?\s*(?:ל|/)\s*שבוע', re.IGNORECASE
)
_PRICE_PER_DAY_RE = re.compile(
    _PRICE_NUMBER + r'\s*(?:₪|ש"ח|שקל|nis)?\s*(?:ל|/)\s*יום(?!ים)', re.IGNORECASE
)
# "חד(?!\w)" excludes construct-state phrases like "חדרי רחצה" (bathrooms)
# or "חדרי שינה" (bedrooms), which aren't the total room count.
ROOMS_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:חדרים|חד(?!\w)['׳]?|rooms?\b)", re.IGNORECASE)
ROOMMATES_RE = re.compile(r"(\d+)\s*שותפ(?:ים|ות)?", re.IGNORECASE)
TOILETS_RE = re.compile(r"(\d+)\s*(?:שירותים|חדרי\s*רחצה)", re.IGNORECASE)
SEPARATE_TOILET_SHOWER_KEYWORDS = [
    "שירותים נפרדים",
    "שירותים ומקלחת נפרדים",
    "מקלחת ושירותים נפרדים",
    "שירותים בנפרד",
    "טואלט נפרד",
]

# How many rooms/spots are being offered RIGHT NOW — distinct from ROOMS_RE
# (the apartment's total size). "2 חדרים פנויים"/"שני חדרים מתפנים" = 2 open
# spots; a bare "חדר פנוי"/"מתפנה חדר" (no number) = 1. Best-effort, like the
# rest of this fallback parser — the LLM path (llm_extractor.py) handles this
# far more reliably.
_HE_NUM_WORDS = {"שני": 2, "שתי": 2, "שלושה": 3, "שלוש": 3, "ארבעה": 4, "ארבע": 4}
_AVAILABLE_ROOMS_NUM_RE = re.compile(
    r"(\d+|" + "|".join(_HE_NUM_WORDS) + r")\s*חדרים\s*(?:פנויים|מתפנים)"
)
_AVAILABLE_ROOMS_ONE_RE = re.compile(r"חדר\s*פנוי|מתפנה\s*חדר")

# Fallback when neither "X חדרים פנויים" nor "חדר פנוי" is stated: count
# bedroom mentions instead ("חדר שינה" -> 1, "שני חדרי שינה" -> 2). Only
# reached when neither explicit-availability pattern above matched, so a
# post that DOES say which room is free ("חדר פנוי בדירת 3 חדרי שינה")
# still correctly returns 1 via the pattern above, not the apartment's
# total bedroom count from this fallback.
_BEDROOM_NUM_RE = re.compile(r"(\d+|" + "|".join(_HE_NUM_WORDS) + r")\s*חדרי\s*שינה")
_BEDROOM_ONE_RE = re.compile(r"חדר\s*שינה(?!\w)")

# "my room"/"החדר שלי" — the poster explicitly offering just their OWN
# single room in a shared apartment (e.g. "Subletting my room ... 3 room
# apartment ... one other roommate"). A strong, direct signal of
# available_rooms=1 regardless of the apartment's total size (rooms, a
# separate field) or how many other roommates already live there (they
# are NOT additional availability). Checked before the bedroom-count
# fallback below, since counting bedroom mentions in a post like this
# would wrongly infer the apartment's total bedroom count (e.g. 3) as
# what's available, rather than just the one room actually being offered.
_MY_ROOM_RE = re.compile(r"\bmy\s+room\b(?!s)|החדר\s*שלי", re.IGNORECASE)


def _extract_available_rooms(text: str) -> int | None:
    match = _AVAILABLE_ROOMS_NUM_RE.search(text)
    if match:
        token = match.group(1)
        return int(token) if token.isdigit() else _HE_NUM_WORDS[token]
    if _AVAILABLE_ROOMS_ONE_RE.search(text):
        return 1
    if _MY_ROOM_RE.search(text):
        return 1
    match = _BEDROOM_NUM_RE.search(text)
    if match:
        token = match.group(1)
        return int(token) if token.isdigit() else _HE_NUM_WORDS[token]
    if _BEDROOM_ONE_RE.search(text):
        return 1
    return None


# Lease duration/dates — best-effort, like the rest of this fallback parser
# (the LLM path handles this far more reliably, including relative phrases
# like "מיידי" this regex approach doesn't attempt at all).
_DURATION_WORD_DAYS = {"שבועיים": 14, "שבוע": 7, "חודשיים": 60, "חודש": 30}
_DURATION_WORD_RE = re.compile(
    "|".join(sorted(_DURATION_WORD_DAYS, key=len, reverse=True))
)
_DURATION_NUM_RE = re.compile(r"(\d+)\s*(ימים|יום|שבועות|שבוע|חודשים|חודש)")
_DURATION_UNIT_DAYS = {"יום": 1, "ימים": 1, "שבוע": 7, "שבועות": 7, "חודש": 30, "חודשים": 30}

_HE_MONTHS = {
    "ינואר": 1, "פברואר": 2, "מרץ": 3, "אפריל": 4, "מאי": 5, "יוני": 6,
    "יולי": 7, "אוגוסט": 8, "ספטמבר": 9, "אוקטובר": 10, "נובמבר": 11, "דצמבר": 12,
}
_HE_MONTH_ALT = "|".join(_HE_MONTHS)
_DATE_TOKEN = r"\d{1,2}[./]\d{1,2}(?:[./]\d{2,4})?"
# A day (or day range, e.g. "27-30") followed by a spelled-out Hebrew month
# name ("27 בספטמבר") — the far more common ordering than "מספטמבר 27"
# (month before day), which isn't attempted here; the LLM path handles
# that phrasing fine, this stays a best-effort fallback like the rest of
# this parser. For a day RANGE before the month ("27-30 באוקטובר"), only
# the first (earlier) day is captured, as a conservative end-date guess.
_DATE_TOKEN_NAMED = rf"\d{{1,2}}(?:\s*-\s*\d{{1,2}})?\s*ב(?:{_HE_MONTH_ALT})"
_DATE_TOKEN_ANY = rf"(?:{_DATE_TOKEN}|{_DATE_TOKEN_NAMED})"
_DATE_RANGE_RE = re.compile(rf"(?:מ-?)?({_DATE_TOKEN_ANY})\s*(?:-|עד|–)\s*({_DATE_TOKEN_ANY})")
# An optional "יום <weekday>" between the prefix and the date itself
# ("החל מיום שישי 25.9" — "starting from [the day] Friday, 25.9") —
# common phrasing that would otherwise stop the date token from being
# recognized at all, since it doesn't come immediately after the prefix.
_HE_WEEKDAY_ALT = "ראשון|שני|שלישי|רביעי|חמישי|שישי|שבת"
_START_DATE_RE = re.compile(
    rf"(?:מ-|החל מ-?|פנוי מ-?|כניסה מ-?)"
    rf"(?:יום\s*(?:{_HE_WEEKDAY_ALT})\s*,?\s*)?"
    rf"({_DATE_TOKEN_ANY})"
)


def _extract_duration_days(text: str) -> int | None:
    match = _DURATION_NUM_RE.search(text)
    if match:
        return int(match.group(1)) * _DURATION_UNIT_DAYS[match.group(2)]
    match = _DURATION_WORD_RE.search(text)
    if match:
        return _DURATION_WORD_DAYS[match.group(0)]
    return None


def _resolve_year(day: int, month: int, today: date) -> int:
    """A bare DD.MM with no year: assume this year, unless that date has
    already passed — then assume next year (sublets are near-term)."""
    try:
        candidate = date(today.year, month, day)
    except ValueError:
        return today.year
    return today.year if candidate >= today else today.year + 1


def _parse_date_token(token: str, today: date) -> date | None:
    token = token.strip()
    named_match = re.match(rf"(\d{{1,2}})(?:\s*-\s*\d{{1,2}})?\s*ב({_HE_MONTH_ALT})", token)
    if named_match:
        day = int(named_match.group(1))
        month = _HE_MONTHS[named_match.group(2)]
        if not (1 <= day <= 31):
            return None
        year = _resolve_year(day, month, today)
        try:
            return date(year, month, day)
        except ValueError:
            return None
    parts = token.split(".") if "." in token else token.split("/")
    if len(parts) < 2:
        return None
    try:
        day, month = int(parts[0]), int(parts[1])
    except ValueError:
        return None
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return None
    if len(parts) > 2 and parts[2]:
        year = int(parts[2])
        if year < 100:
            year += 2000
    else:
        year = _resolve_year(day, month, today)
    try:
        return date(year, month, day)
    except ValueError:
        return None


def _extract_lease_dates(
    text: str, today: date | None = None
) -> tuple[date | None, date | None, int | None]:
    """(start_date, end_date, duration_days) best-effort from the post
    text — whichever of a date range, a bare start date, or a stated
    duration is present. listing_filters._resolve_dates reconciles
    whatever combination this (or the LLM path) returns."""
    today = today or date.today()
    range_match = _DATE_RANGE_RE.search(text)
    if range_match:
        start = _parse_date_token(range_match.group(1), today)
        end = _parse_date_token(range_match.group(2), today)
        return start, end, None
    start_match = _START_DATE_RE.search(text)
    start = _parse_date_token(start_match.group(1), today) if start_match else None
    return start, None, _extract_duration_days(text)


# Israeli mobile numbers, tolerating spaces/dots/dashes and a +972/972/0
# prefix. Best-effort — used only when the LLM path (llm_extractor.py) isn't
# available, mirroring bgu-housing-bot's _normalize_phone.
_PHONE_CHUNK_RE = re.compile(r"(?:\+?972|0)[\d\s().\-]{7,}")


def _extract_phone(text: str) -> str | None:
    for chunk in _PHONE_CHUNK_RE.findall(text):
        digits = re.sub(r"\D", "", chunk)
        if digits.startswith("972"):
            digits = "0" + digits[3:]
        if len(digits) == 10 and digits.startswith("05"):
            return f"{digits[:3]}-{digits[3:]}"
    return None


# A weak fallback address heuristic: "<Hebrew word(s)> <house number>", e.g.
# "דיזנגוף 12" or "רוטשילד 45". Only used when the LLM path isn't available
# (llm_extractor.py does a far more reliable job of this). Common
# non-address phrases that follow the same shape ("קומה 3", "3 דקות") are
# excluded via a small stoplist to cut down on false positives.
_ADDRESS_RE = re.compile(r"([א-ת]{2,}(?:\s[א-ת]{2,}){0,2})\s+(\d{1,3})\b")
# "מעקב לפני 2 שעות" ("Follow · 2 hours ago") — Facebook's own post-header
# UI text, captured as part of the post's raw_text — matches this regex's
# shape (Hebrew word(s) + a number) just as well as a real street address,
# and the "N hours/days ago" portion changes on every later scan, which
# poisons content_hash_key's repost-matching (see store.py) into never
# matching itself across scans and getting re-alerted every time.
_ADDRESS_STOPWORDS = {
    "קומה",
    "חדרים",
    "חדר",
    "דקות",
    "דקה",
    "מטר",
    "מטרים",
    "שותפים",
    "שותף",
    "לפני",
    "מעקב",
}


def _extract_address(text: str) -> str | None:
    for match in _ADDRESS_RE.finditer(text):
        words = match.group(1).split()
        if words and words[-1] in _ADDRESS_STOPWORDS:
            continue
        return f"{match.group(1)} {match.group(2)}"
    return None


def is_offer_listing(text: str) -> bool:
    """True if a post looks like someone OFFERING a sublet (not seeking one)."""
    lowered = text.lower()
    if any(k.lower() in lowered for k in SEEKER_KEYWORDS):
        return False
    return any(k.lower() in lowered for k in OFFER_KEYWORDS)


# Deliberately narrower than SEEKER_KEYWORDS/is_offer_listing: the seeker verb
# must be immediately followed by "apartment"/"sublet" itself, not just occur
# anywhere in the post. This excludes the very common "מחפש/ת שותף" ("looking
# for a roommate") pattern, which is usually someone OFFERING a room in their
# own apartment, not seeking one — a plain SEEKER_KEYWORDS match would wrongly
# treat that as a non-offer. Used only to skip a paced/budgeted LLM call for a
# post that's near-certainly not an offer (see cli._extract_listing); every
# other post — including "looking for a roommate" ones — still goes to the
# LLM, which remains the source of truth for anything ambiguous.
_EXPLICIT_APARTMENT_SEEKER_RE = re.compile(
    r"(?:מחפש|מחפשת|מחפשים|looking for|searching for)\s+"
    r"(?:דירה|סאבלט|סבלט|an?\s+apartment|a\s+sublet|apartment|sublet)",
    re.IGNORECASE,
)


def looks_like_explicit_apartment_seeker(text: str) -> bool:
    """True only for an explicit "I'm looking for an apartment/sublet"
    phrasing — see _EXPLICIT_APARTMENT_SEEKER_RE for why this is narrower
    than is_offer_listing()'s SEEKER_KEYWORDS check."""
    return bool(_EXPLICIT_APARTMENT_SEEKER_RE.search(text or ""))


def _extract_price(text: str, duration_days: int | None = None) -> int | None:
    week_match = _PRICE_PER_WEEK_RE.search(text)
    if week_match:
        rate = int(week_match.group(1).replace(",", "").replace(".", ""))
        return round(rate * duration_days / 7) if duration_days else rate
    day_match = _PRICE_PER_DAY_RE.search(text)
    if day_match:
        rate = int(day_match.group(1).replace(",", "").replace(".", ""))
        return rate * duration_days if duration_days else rate
    match = PRICE_RE.search(text)
    if not match:
        return None
    # Exactly one of the three alternatives' groups is populated, depending
    # on which one matched (currency marker / "per month" phrase / "price:"
    # label) — see PRICE_RE.
    raw = next(g for g in match.groups() if g is not None)
    return int(raw.replace(",", "").replace(".", ""))


def _extract_rooms(text: str) -> float | None:
    match = ROOMS_RE.search(text)
    if not match:
        return None
    return float(match.group(1))


def _matched_neighborhoods(text: str, neighborhoods: list[str]) -> list[str]:
    lowered = text.lower()
    return [n for n in neighborhoods if n.lower() in lowered]


def _extract_roommates(text: str) -> int | None:
    match = ROOMMATES_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def _extract_toilets(text: str) -> int | None:
    match = TOILETS_RE.search(text)
    if not match:
        return None
    return int(match.group(1))


def _has_separate_toilet_shower(text: str) -> bool:
    lowered = text.lower()
    return any(k.lower() in lowered for k in SEPARATE_TOILET_SHOWER_KEYWORDS)


EXCERPT_LIMIT = 300


def _summarize(text: str) -> str:
    """A trimmed excerpt of the raw text — the fallback summary when the LLM
    path (which writes a real one-line summary) isn't available."""
    excerpt = " ".join(text.split())
    if len(excerpt) > EXCERPT_LIMIT:
        excerpt = excerpt[:EXCERPT_LIMIT] + "…"
    return excerpt


def parse_listing(
    text: str,
    post_url: str,
    group_name: str,
    known_neighborhoods: list[str],
    images: list[str] | None = None,
) -> Listing:
    address = _extract_address(text)
    start, end, duration = _extract_lease_dates(text)
    return Listing(
        post_url=post_url,
        group_name=group_name,
        raw_text=text,
        price=_extract_price(text, duration_days=duration),
        rooms=_extract_rooms(text),
        neighborhoods_mentioned=_matched_neighborhoods(text, known_neighborhoods),
        roommates=_extract_roommates(text),
        toilets=_extract_toilets(text),
        separate_toilet_shower=_has_separate_toilet_shower(text),
        available_rooms=_extract_available_rooms(text),
        address=address,
        phone=_extract_phone(text),
        images=images or [],
        summary=_summarize(text),
        lease_start_date=start,
        lease_end_date=end,
        lease_duration_days=duration,
    )
