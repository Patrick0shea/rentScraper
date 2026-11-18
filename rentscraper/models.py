"""Core data model for a scraped rental listing."""
from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

# Accommodation kinds
ENTIRE = "entire"
SHARED = "shared"  # a room (or bed) in a shared property
UNKNOWN = "unknown"

# Preference tiers (lower is better)
TIER_THREE_BED = 1
TIER_TWO_BED = 2
TIER_SHARED = 3
TIER_OTHER = 9

TIER_LABELS = {
    TIER_THREE_BED: "3+ bed entire property",
    TIER_TWO_BED: "2 bed entire property (sofa bed needed)",
    TIER_SHARED: "Shared accommodation",
    TIER_OTHER: "Not suitable for 3 people",
}


@dataclass
class Listing:
    """A single advertisement as published by a source website.

    Only fields actually present in the source data are filled in; anything
    unknown stays ``None``. Nothing is ever guessed or invented.
    """

    source: str
    source_id: str
    url: str
    title: str
    rent_monthly_eur: Optional[float] = None
    rent_text: Optional[str] = None
    address: Optional[str] = None
    bedrooms: Optional[int] = None
    bathrooms: Optional[int] = None
    property_type: Optional[str] = None
    description: Optional[str] = None
    accommodation: str = UNKNOWN  # ENTIRE / SHARED / UNKNOWN
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    coords_approximate: bool = False
    available_from: Optional[str] = None  # ISO date when stated by the source
    available_to: Optional[str] = None
    date_found: Optional[str] = None  # ISO timestamp first seen by this scraper
    date_scraped: Optional[str] = None  # ISO timestamp of this observation
    listed_on: Optional[str] = None  # date the site says it was listed/refreshed
    extra: dict[str, Any] = field(default_factory=dict)

    # --- derived fields (filled in by the analysis pipeline) ---
    area: Optional[str] = None
    area_priority: int = 0  # 3 named priority area, 2 priority district, 1 secondary district, 0 other
    distances_km: dict[str, float] = field(default_factory=dict)
    total_monthly_for_group_eur: Optional[float] = None
    cost_per_person_eur: Optional[float] = None
    tier: int = TIER_OTHER
    within_budget: Optional[bool] = None
    availability_flags: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    score: Optional[float] = None
    duplicate_group: Optional[str] = None
    duplicate_urls: list[str] = field(default_factory=list)
    status: str = "active"
    price_change: Optional[str] = None
    is_new: bool = False
    contacted: bool = False  # marked by the user; hidden from shortlist and updates

    @property
    def uid(self) -> str:
        """Stable identifier for this advert on this source."""
        return f"{self.source}:{self.source_id}"

    @property
    def tier_label(self) -> str:
        return TIER_LABELS.get(self.tier, "")

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["uid"] = self.uid
        d["tier_label"] = self.tier_label
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Listing":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


def stable_id(*parts: Any) -> str:
    """Short deterministic hash used when a source has no native listing id."""
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]
