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
class SearchConfig:
    """Your criteria for the apartment you're looking to sublet FROM someone."""

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
    facebook_groups: list[FacebookGroup]
    posts_per_group: int
    search: SearchConfig
    telegram: TelegramConfig | None


def load_config(path: Path | None = None) -> Config:
    path = path or (ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    search_raw = raw.get("search") or {}
    search = SearchConfig(
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

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")
    telegram = TelegramConfig(bot_token, chat_id) if bot_token and chat_id else None

    return Config(
        facebook_groups=[FacebookGroup(**g) for g in raw["facebook_groups"]],
        posts_per_group=raw["posts_per_group"],
        search=search,
        telegram=telegram,
    )
