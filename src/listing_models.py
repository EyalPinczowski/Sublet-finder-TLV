from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Listing:
    post_url: str
    group_name: str
    raw_text: str
    price: int | None = None
    rooms: float | None = None
    neighborhoods_mentioned: list[str] = field(default_factory=list)
    roommates: int | None = None
    toilets: int | None = None
    separate_toilet_shower: bool = False
