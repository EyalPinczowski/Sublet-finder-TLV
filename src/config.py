from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


@dataclass
class FacebookGroup:
    name: str
    url: str


@dataclass
class ApartmentSearchConfig:
    """Your own criteria when looking for an apartment to move INTO — the
    mirror of `apartment`, which is what you're subletting OUT."""

    price_min: int | None = None
    price_max: int | None = None
    min_rooms: float | None = None
    neighborhoods: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    max_roommates: int | None = None
    min_bathrooms: int | None = None
    separate_toilet_shower_max_roommates: int | None = None


@dataclass
class TelegramConfig:
    bot_token: str
    chat_id: str


@dataclass
class Config:
    apartment: dict
    facebook_groups: list[FacebookGroup]
    search_keywords: list[str]
    posts_per_group: int
    min_fit_score: int
    gemini_api_key: str
    apartment_search: ApartmentSearchConfig
    telegram: TelegramConfig | None

    @property
    def apartment_summary(self) -> str:
        a = self.apartment
        lines = [
            f"Location: {a['neighborhood']}, {a['city']}",
            f"Rooms: {a['rooms']}",
            f"Price: {a['price_ils_per_month']} ILS/month",
            f"Available: {a['available_from']} to {a['available_until']}",
            f"Furnished: {a['furnished']}",
            f"Pets allowed: {a['pets_allowed']}",
            f"Amenities: {', '.join(a.get('amenities', []))}",
            f"Description: {a['description'].strip()}",
        ]
        return "\n".join(lines)


def load_config(path: Path | None = None) -> Config:
    path = path or (ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    api_key = os.environ.get("GEMINI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not set. Copy .env.example to .env and fill it in "
            "with a free key from https://aistudio.google.com/apikey"
        )

    search_raw = raw.get("apartment_search") or {}
    apartment_search = ApartmentSearchConfig(
        price_min=search_raw.get("price_min"),
        price_max=search_raw.get("price_max"),
        min_rooms=search_raw.get("min_rooms"),
        neighborhoods=search_raw.get("neighborhoods") or [],
        excluded_keywords=search_raw.get("excluded_keywords") or [],
        max_roommates=search_raw.get("max_roommates"),
        min_bathrooms=search_raw.get("min_bathrooms"),
        separate_toilet_shower_max_roommates=search_raw.get(
            "separate_toilet_shower_max_roommates"
        ),
    )

    telegram_raw = raw.get("telegram")
    telegram = TelegramConfig(**telegram_raw) if telegram_raw else None

    return Config(
        apartment=raw["apartment"],
        facebook_groups=[FacebookGroup(**g) for g in raw["facebook_groups"]],
        search_keywords=raw["search_keywords"],
        posts_per_group=raw["posts_per_group"],
        min_fit_score=raw["min_fit_score"],
        gemini_api_key=api_key,
        apartment_search=apartment_search,
        telegram=telegram,
    )
