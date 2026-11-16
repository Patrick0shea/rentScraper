"""Enrichment, classification, budget filtering, availability flags and scoring."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Optional

from .geo import approximate_coords, dublin_district, haversine_km, match_area
from .models import (
    ENTIRE,
    SHARED,
    TIER_OTHER,
    TIER_SHARED,
    TIER_THREE_BED,
    TIER_TWO_BED,
    UNKNOWN,
    Listing,
)
from .parsing import parse_date

SHARED_PATTERNS = re.compile(
    r"\b(room (?:to rent|for rent|available)|house ?share|flat ?share|shared (?:house|apartment|flat|room)|"
    r"double room|single room|twin room|bed in|room in (?:a )?shared|lodger|digs|owner occupied|live-in landlord)\b",
    re.I,
)

# Platforms where the tenant picks move-in/move-out dates when booking.
MID_TERM_SOURCES = ("spotahome", "housinganywhere")

# Words that count as "hard" availability problems (score penalty applied)
HARD_FLAG_PREFIXES = ("Available only from", "Available only until", "Minimum lease", "Advertised as long-term")


def classify_accommodation(lst: Listing) -> str:
    if lst.accommodation in (ENTIRE, SHARED):
        # A source-provided "entire" can still be a room ad on general sites.
        if lst.accommodation == ENTIRE and lst.source in ("daft", "propertyie", "rentie", "roomsforrent"):
            if SHARED_PATTERNS.search(f"{lst.title} {lst.property_type or ''}"):
                return SHARED
        return lst.accommodation
    text = f"{lst.title} {lst.property_type or ''} {lst.description or ''}"
    return SHARED if SHARED_PATTERNS.search(text) else (ENTIRE if lst.bedrooms else UNKNOWN)


def _months(n: int, unit: str) -> int:
    unit = unit.lower()
    if unit.startswith("year"):
        return n * 12
    if unit.startswith("week"):
        return max(1, round(n / 4.33))
    return n


def availability_flags(lst: Listing, start: date, end: date, today: Optional[date] = None) -> list[str]:
    """Flags explaining why a listing may not cover the whole rental period."""
    today = today or date.today()
    flags: list[str] = []
    text = " ".join(filter(None, [lst.title, lst.description or ""]))
    low = text.lower()
    period_months = (end.year - start.year) * 12 + end.month - start.month + 1

    avail_from = date.fromisoformat(lst.available_from) if lst.available_from else None
    if avail_from is None:
        m = re.search(r"available (?:from|on)\s+(\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?|[a-z]+\s+\d{4}|\d{1,2}/\d{1,2}/\d{2,4})", low)
        if m:
            d = parse_date(m.group(1), default_year=start.year)
            if d:
                avail_from = d
    if avail_from:
        if avail_from > start + timedelta(days=14):
            flags.append(f"Available only from {avail_from:%d %b %Y} (after {start:%d %b %Y})")
        elif avail_from < start - timedelta(days=21) and lst.source not in MID_TERM_SOURCES:
            flags.append(
                f"Available from {avail_from:%d %b %Y} – landlord may expect rent from before January"
            )
    elif re.search(r"\bavailable (?:now|immediately)\b|\bimmediate(?:ly)? available\b", low):
        flags.append("Available now – landlord may expect rent from before January")

    avail_to = date.fromisoformat(lst.available_to) if lst.available_to else None
    if avail_to is None:
        m = re.search(r"(?:available )?(?:until|till|til|up to)\s+(?:the\s+)?(?:end of\s+)?([a-z]+(?:\s+\d{4})?|\d{1,2}(?:st|nd|rd|th)?\s+[a-z]+(?:\s+\d{4})?)", low)
        if m and not re.match(r"(?:now|further|you|the|a|an|and|is|it|we)\b", m.group(1)):
            phrase = m.group(1)
            seasons = {"spring": (5, 31), "summer": (8, 31), "autumn": (11, 30), "winter": (2, 28)}
            season = next((s for s in seasons if phrase.startswith(s)), None)
            if season:
                yr = re.search(r"\d{4}", phrase)
                mon, day = seasons[season]
                try:
                    avail_to = date(int(yr.group(0)) if yr else start.year, mon, day)
                except ValueError:
                    avail_to = None
                if season == "spring":
                    flags.append(f"Advert says available until {phrase} – confirm it runs to {end:%d %b %Y}")
                    avail_to = None
            else:
                d = parse_date(phrase, default_year=start.year)
                if d and d.year >= today.year and d < end:
                    avail_to = d
    if avail_to and avail_to < end:
        flags.append(f"Available only until {avail_to:%d %b %Y} (need until {end:%d %b %Y})")

    min_lease = None
    for m in re.finditer(
        r"(?:minimum|min\.?|at least)\s*(?:of\s*)?(?:a\s*)?(\d{1,2})\s*[- ]?\s*(month|year|week)s?"
        r"|(\d{1,2})\s*[- ]?\s*(month|year)s?\s*(?:minimum\s*)?(?:lease|contract|tenancy|let)\b",
        low,
    ):
        n = int(m.group(1) or m.group(3))
        unit = m.group(2) or m.group(4)
        months = _months(n, unit)
        min_lease = max(min_lease or 0, months)
    if lst.extra.get("minimum_stay"):
        m = re.match(r"(\d+)\s*(\w+)", str(lst.extra["minimum_stay"]))
        if m:
            min_lease = max(min_lease or 0, _months(int(m.group(1)), m.group(2)))
    if min_lease and min_lease > period_months:
        flags.append(f"Minimum lease appears to be {min_lease} months (Jan–May is {period_months})")
    elif re.search(r"\blong[- ]term (?:let|lease|rental|tenan)", low):
        flags.append("Advertised as long-term let – a 5-month lease may not be accepted")

    if re.search(r"\bshort[- ]term\b|\bshort[- ]let\b|\bflexible (?:lease|term)\b|\bmid[- ]term\b", low):
        lst.notes.append("Advert mentions short/flexible-term letting")

    if not flags and not avail_from and not avail_to:
        if lst.source in MID_TERM_SOURCES:
            flags.append("Dates not stated in search data – check availability for Jan–May 2027 on the site")
        else:
            flags.append("Jan–May 2027 availability not stated – most Irish lets expect 12 months; confirm with landlord")
    return flags


def enrich(lst: Listing, cfg: dict, today: Optional[date] = None) -> Listing:
    s = cfg["search"]
    occupants = int(s.get("occupants", 3))
    max_total = float(s["max_total_monthly_rent_eur"])
    max_pp = float(s["max_per_person_monthly_eur"])
    start = date.fromisoformat(s["rental_start"])
    end = date.fromisoformat(s["rental_end"])

    text_for_area = " ".join(filter(None, [lst.address, lst.title, lst.extra.get("locality")]))
    lst.area = match_area(text_for_area, cfg.get("priority_areas", []))
    district = dublin_district(text_for_area)
    if lst.area:
        lst.area_priority = 3
    elif district in cfg.get("priority_districts", []):
        lst.area_priority = 2
    elif district in cfg.get("secondary_districts", []):
        lst.area_priority = 1
    else:
        lst.area_priority = 0
    if district:
        lst.area = f"{lst.area} ({district})" if lst.area else district

    if lst.latitude is None or lst.longitude is None:
        approx = approximate_coords(text_for_area)
        if approx:
            lst.latitude, lst.longitude = approx
            lst.coords_approximate = True
    if lst.latitude is not None and lst.longitude is not None:
        lst.distances_km = {
            lm["name"]: round(haversine_km(lst.latitude, lst.longitude, lm["lat"], lm["lon"]), 2)
            for lm in cfg.get("landmarks", [])
        }

    lst.accommodation = classify_accommodation(lst)

    rent = lst.rent_monthly_eur
    if rent is not None:
        if lst.accommodation == SHARED:
            # Price is per room/bed: three people need three of them.
            lst.cost_per_person_eur = round(rent, 2)
            lst.total_monthly_for_group_eur = round(rent * occupants, 2)
            lst.notes.append(f"Price is per room – {occupants} rooms needed (assumes same price each)")
            if lst.extra.get("bed_in_shared_room"):
                lst.notes.append("This is a bed in a shared bedroom")
        else:
            lst.total_monthly_for_group_eur = round(rent, 2)
            lst.cost_per_person_eur = round(rent / occupants, 2)
        lst.within_budget = lst.total_monthly_for_group_eur <= max_total and lst.cost_per_person_eur <= max_pp
    else:
        lst.within_budget = None
        lst.notes.append("No price stated")

    if lst.accommodation == SHARED:
        lst.tier = TIER_SHARED
    elif lst.accommodation == ENTIRE and lst.bedrooms is not None and lst.bedrooms >= 3:
        lst.tier = TIER_THREE_BED
    elif lst.accommodation == ENTIRE and lst.bedrooms == 2:
        lst.tier = TIER_TWO_BED
        lst.notes.append("2 bed – third person needs a sofa bed or similar; check living room suits")
    else:
        lst.tier = TIER_OTHER

    if lst.extra.get("price_is_from"):
        lst.notes.append("Spotahome shows a 'from' price; actual price can depend on dates")
    lst.availability_flags = availability_flags(lst, start, end, today)
    lst.score = score(lst, cfg)
    return lst


def _lin(value: float, best: float, worst: float) -> float:
    if best == worst:
        return 1.0
    x = (worst - value) / (worst - best)
    return max(0.0, min(1.0, x))


def score(lst: Listing, cfg: dict) -> Optional[float]:
    """0-100 score. Higher is better. None when there is no price."""
    if lst.cost_per_person_eur is None:
        return None
    sc = cfg.get("scoring", {})
    w = sc.get("weights", {"price": 0.35, "bedrooms": 0.3, "proximity": 0.25, "area": 0.1})
    max_pp = float(cfg["search"]["max_per_person_monthly_eur"])
    price_s = _lin(lst.cost_per_person_eur, max_pp * 0.6, max_pp) if lst.cost_per_person_eur <= max_pp else 0.0
    bed_s = {TIER_THREE_BED: 1.0, TIER_TWO_BED: 0.6, TIER_SHARED: 0.25}.get(lst.tier, 0.0)
    if lst.distances_km:
        avg = sum(lst.distances_km.values()) / len(lst.distances_km)
        prox_s = _lin(avg, sc.get("proximity_full_score_km", 1.5), sc.get("proximity_zero_score_km", 8.0))
        if lst.coords_approximate:
            prox_s *= 0.9
    else:
        prox_s = 0.2
    area_s = {3: 1.0, 2: 0.75, 1: 0.35}.get(lst.area_priority, 0.0)
    total = 100 * (w["price"] * price_s + w["bedrooms"] * bed_s + w["proximity"] * prox_s + w["area"] * area_s)
    if any(f.startswith(HARD_FLAG_PREFIXES) for f in lst.availability_flags):
        total -= sc.get("availability_risk_penalty", 8)
    if lst.tier == TIER_SHARED:
        total -= sc.get("shared_penalty", 0)
    return round(max(0.0, total), 1)


def avg_distance(lst: Listing) -> Optional[float]:
    if not lst.distances_km:
        return None
    return round(sum(lst.distances_km.values()) / len(lst.distances_km), 2)


def is_shortlisted(lst: Listing, cfg: dict) -> bool:
    """Matches the group's requirements: budget, size, distance."""
    s = cfg["search"]
    if not lst.within_budget:
        return False
    if lst.tier == TIER_OTHER and not s.get("include_one_bed_and_studios", False):
        return False
    if lst.status != "active" or (lst.duplicate_group and lst.extra.get("_duplicate_secondary")):
        return False
    if lst.available_from:
        # Not usable if it only frees up in the last month of the period (or later).
        if date.fromisoformat(lst.available_from) > date.fromisoformat(s["rental_end"]) - timedelta(days=30):
            return False
    d = avg_distance(lst)
    max_d = s.get("max_distance_km")
    if max_d and d is not None and d > max_d:
        return False
    return True
