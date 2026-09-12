from __future__ import annotations

import os
from dataclasses import dataclass
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
class Config:
    apartment: dict
    facebook_groups: list[FacebookGroup]
    search_keywords: list[str]
    posts_per_group: int
    min_fit_score: int
    gemini_api_key: str

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

    return Config(
        apartment=raw["apartment"],
        facebook_groups=[FacebookGroup(**g) for g in raw["facebook_groups"]],
        search_keywords=raw["search_keywords"],
        posts_per_group=raw["posts_per_group"],
        min_fit_score=raw["min_fit_score"],
        gemini_api_key=api_key,
    )
