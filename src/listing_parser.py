from __future__ import annotations

import re

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
# partial substring of a longer number.
PRICE_RE = re.compile(
    r'(?<!\d)(\d{1,3}(?:[,.]\d{3})+|\d{2,6})(?!\d)\s*(?:₪|ש"ח|שקל|nis)', re.IGNORECASE
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
_ADDRESS_STOPWORDS = {"קומה", "חדרים", "חדר", "דקות", "דקה", "מטר", "מטרים", "שותפים", "שותף"}


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


def _extract_price(text: str) -> int | None:
    match = PRICE_RE.search(text)
    if not match:
        return None
    return int(match.group(1).replace(",", "").replace(".", ""))


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
    return Listing(
        post_url=post_url,
        group_name=group_name,
        raw_text=text,
        price=_extract_price(text),
        rooms=_extract_rooms(text),
        neighborhoods_mentioned=_matched_neighborhoods(text, known_neighborhoods),
        roommates=_extract_roommates(text),
        toilets=_extract_toilets(text),
        separate_toilet_shower=_has_separate_toilet_shower(text),
        address=address,
        phone=_extract_phone(text),
        images=images or [],
        summary=_summarize(text),
    )
