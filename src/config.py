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
    """One named set of criteria for the apartment you're looking to sublet
    FROM someone — e.g. a "single room" profile and a separate "two rooms"
    profile for searching with a friend. Every post is checked against every
    configured profile in one pass (see config.yaml's `searches:` list)."""

    name: str = "default"
    # Emoji prefix on this profile's Telegram alerts, so two profiles read as
    # visually distinct at a glance (Telegram has no literal text-color API).
    emoji: str = "\U0001F3E0"
    price_min: int | None = None
    price_max: int | None = None
    min_rooms: float | None = None
    neighborhoods: list[str] = field(default_factory=list)
    excluded_keywords: list[str] = field(default_factory=list)
    max_roommates: int | None = None
    min_bathrooms: int | None = None
    separate_toilet_shower_max_roommates: int | None = None
    # How many rooms/spots the POST must be offering right now — distinct
    # from min_rooms (the apartment's total size). None = no constraint.
    min_available_rooms: int | None = None
    max_available_rooms: int | None = None


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
    against, in addition to (not instead of) a profile's neighborhoods."""

    target_label: str = ""
    target_lat: float | None = None
    target_lon: float | None = None
    max_distance_meters: float = 1000

    @property
    def active(self) -> bool:
        return self.target_lat is not None and self.target_lon is not None


@dataclass
class StayConfig:
    """How long a stay must be, and how soon it must start — global, not
    per-profile, since these are about when you can personally move, not
    about room count."""

    min_days: int = 14
    # Only listings whose lease starts within [today, today + this] count.
    search_window_days: int = 21


@dataclass
class ScanWindowConfig:
    """How far back a scan looks. The first scan ever run looks back this
    many days; every scan after that looks back to the last successful
    scan instead (self-healing if a run was missed), but never further
    back than this many days even after a long outage — see
    src/cli.py's `_compute_cutoff`."""

    initial_lookback_days: int = 4


@dataclass
class Config:
    facebook_groups: list[FacebookGroup]
    posts_per_group: int
    searches: list[SearchConfig]
    telegram: TelegramConfig | None
    llm: LLMConfig
    zone: ZoneConfig
    stay: StayConfig
    scan_window: ScanWindowConfig

    @property
    def all_neighborhoods(self) -> list[str]:
        """The union of every profile's neighborhood list — used at
        extraction time so a post's neighborhoods_mentioned covers whatever
        any profile might care about; each profile then filters that down
        to its own list when matching (see listing_filters.matches)."""
        seen: list[str] = []
        for profile in self.searches:
            for n in profile.neighborhoods:
                if n not in seen:
                    seen.append(n)
        return seen


def _search_profile(raw: dict, default_name: str = "default") -> SearchConfig:
    return SearchConfig(
        name=raw.get("name", default_name),
        emoji=raw.get("emoji", "\U0001F3E0"),
        price_min=raw.get("price_min"),
        price_max=raw.get("price_max"),
        min_rooms=raw.get("min_rooms"),
        neighborhoods=raw.get("neighborhoods") or [],
        excluded_keywords=raw.get("excluded_keywords") or [],
        max_roommates=raw.get("max_roommates"),
        min_bathrooms=raw.get("min_bathrooms"),
        separate_toilet_shower_max_roommates=raw.get("separate_toilet_shower_max_roommates"),
        min_available_rooms=raw.get("min_available_rooms"),
        max_available_rooms=raw.get("max_available_rooms"),
    )


def load_config(path: Path | None = None) -> Config:
    path = path or (ROOT / "config.yaml")
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)

    if "searches" in raw:
        searches = [_search_profile(s) for s in raw["searches"]]
    else:
        # Legacy single `search:` block — wrap it as one profile so old
        # config files keep working unchanged.
        searches = [_search_profile(raw.get("search") or {})]

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

    stay_raw = raw.get("stay") or {}
    stay = StayConfig(
        min_days=stay_raw.get("min_days", 14),
        search_window_days=stay_raw.get("search_window_days", 21),
    )

    scan_window_raw = raw.get("scan_window") or {}
    scan_window = ScanWindowConfig(
        initial_lookback_days=scan_window_raw.get("initial_lookback_days", 4),
    )

    config = Config(
        facebook_groups=[FacebookGroup(**g) for g in raw["facebook_groups"]],
        posts_per_group=raw["posts_per_group"],
        searches=searches,
        telegram=telegram,
        llm=llm,
        zone=zone,
        stay=stay,
        scan_window=scan_window,
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
    if not config.searches:
        problems.append("searches is empty — nothing to match against")
    names = [p.name for p in config.searches]
    if len(names) != len(set(names)):
        problems.append(f"search profile names must be unique, got: {names}")
    for profile in config.searches:
        if (
            profile.price_min is not None
            and profile.price_max is not None
            and profile.price_min > profile.price_max
        ):
            problems.append(
                f"searches[{profile.name!r}].price_min ({profile.price_min}) > "
                f"price_max ({profile.price_max})"
            )
        if (
            profile.min_available_rooms is not None
            and profile.max_available_rooms is not None
            and profile.min_available_rooms > profile.max_available_rooms
        ):
            problems.append(
                f"searches[{profile.name!r}].min_available_rooms "
                f"({profile.min_available_rooms}) > max_available_rooms "
                f"({profile.max_available_rooms})"
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
    if config.stay.min_days <= 0:
        problems.append(f"stay.min_days ({config.stay.min_days}) must be > 0")
    if config.stay.search_window_days <= 0:
        problems.append(
            f"stay.search_window_days ({config.stay.search_window_days}) must be > 0"
        )
    if config.scan_window.initial_lookback_days <= 0:
        problems.append(
            f"scan_window.initial_lookback_days "
            f"({config.scan_window.initial_lookback_days}) must be > 0"
        )
    if problems:
        raise SystemExit("config error — fix config.yaml:\n  - " + "\n  - ".join(problems))
