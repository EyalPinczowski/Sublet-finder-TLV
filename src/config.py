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
class LLMConfig:
    """Gemini-based extraction settings. See src/llm_extractor.py.

    api_key is None (feature off) unless GEMINI_API_KEY is set in the
    environment — the key itself never lives in config.yaml.
    """

    enabled: bool = True
    daily_budget: int = 400
    min_interval_seconds: float = 4.5
    api_key: str | None = None

    @property
    def active(self) -> bool:
        return self.enabled and bool(self.api_key)


@dataclass
class ZoneConfig:
    """A single target point + straight-line radius a listing is scored
    against, in addition to (not instead of) search.neighborhoods."""

    target_label: str = ""
    target_lat: float | None = None
    target_lon: float | None = None
    max_distance_meters: float = 1000

    @property
    def active(self) -> bool:
        return self.target_lat is not None and self.target_lon is not None


@dataclass
class Config:
    facebook_groups: list[FacebookGroup]
    posts_per_group: int
    search: SearchConfig
    telegram: TelegramConfig | None
    llm: LLMConfig
    zone: ZoneConfig


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

    llm_raw = raw.get("llm") or {}
    llm = LLMConfig(
        enabled=llm_raw.get("enabled", True),
        daily_budget=llm_raw.get("daily_budget", 400),
        min_interval_seconds=llm_raw.get("min_interval_seconds", 4.5),
        api_key=os.environ.get("GEMINI_API_KEY") or None,
    )

    zone_raw = raw.get("zone") or {}
    zone = ZoneConfig(
        target_label=zone_raw.get("target_label", ""),
        target_lat=zone_raw.get("target_lat"),
        target_lon=zone_raw.get("target_lon"),
        max_distance_meters=zone_raw.get("max_distance_meters", 1000),
    )

    config = Config(
        facebook_groups=[FacebookGroup(**g) for g in raw["facebook_groups"]],
        posts_per_group=raw["posts_per_group"],
        search=search,
        telegram=telegram,
        llm=llm,
        zone=zone,
    )
    validate(config)
    return config


def validate(config: Config) -> None:
    """Fail fast on an obviously-broken config, with a clear message."""
    problems = []
    if not config.facebook_groups:
        problems.append("facebook_groups is empty — nothing to scan")
    if config.posts_per_group <= 0:
        problems.append(f"posts_per_group ({config.posts_per_group}) must be > 0")
    if (
        config.search.price_min is not None
        and config.search.price_max is not None
        and config.search.price_min > config.search.price_max
    ):
        problems.append(
            f"search.price_min ({config.search.price_min}) > "
            f"search.price_max ({config.search.price_max})"
        )
    if config.zone.active and config.zone.max_distance_meters <= 0:
        problems.append(
            f"zone.max_distance_meters ({config.zone.max_distance_meters}) must be > 0"
        )
    if config.zone.active and not (
        -90 <= config.zone.target_lat <= 90 and -180 <= config.zone.target_lon <= 180
    ):
        problems.append(
            f"zone target ({config.zone.target_lat}, {config.zone.target_lon}) "
            "is not a valid lat/lon"
        )
    if config.llm.daily_budget < 0:
        problems.append(f"llm.daily_budget ({config.llm.daily_budget}) must be >= 0")
    if problems:
        raise SystemExit("config error — fix config.yaml:\n  - " + "\n  - ".join(problems))
