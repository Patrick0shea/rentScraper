"""Duplicate detection within and across sources.

Two listings are treated as the same property when they have compatible
bedroom counts, prices within a tolerance, and either
  * precise coordinates within ``max_distance_m``, or
  * normalised addresses that are very similar.
Within one source, only exact re-posts (same normalised address, bedrooms and
price) are merged, so distinct units in one building are not hidden.
"""
from __future__ import annotations

import hashlib
import re
from difflib import SequenceMatcher
from typing import Optional

from .geo import haversine_km
from .models import Listing

_STOP = {
    "co", "county", "dublin", "ireland", "the", "apartment", "apt", "unit", "flat", "house",
    "road", "rd", "street", "st", "avenue", "ave", "court", "ct",
}
_ABBREV = {"rd": "road", "st": "street", "ave": "avenue", "ct": "court", "dk": "dock", "sq": "square"}


def normalise_address(text: Optional[str]) -> str:
    if not text:
        return ""
    t = text.lower()
    t = re.sub(r"\bd(\d{2})\s?[a-z0-9]{4}\b", r"d\1", t)  # Eircode -> routing key
    t = re.sub(r"[^a-z0-9 ]+", " ", t)
    words = [_ABBREV.get(w, w) for w in t.split()]
    return " ".join(w for w in words if w not in _STOP)


def address_similarity(a: Optional[str], b: Optional[str]) -> float:
    na, nb = normalise_address(a), normalise_address(b)
    if not na or not nb:
        return 0.0
    ta, tb = set(na.split()), set(nb.split())
    jaccard = len(ta & tb) / len(ta | tb) if ta | tb else 0.0
    return max(jaccard, SequenceMatcher(None, na, nb).ratio())


def _price_close(a: Optional[float], b: Optional[float], pct: float) -> bool:
    if a is None or b is None:
        return False
    return abs(a - b) <= max(a, b) * pct / 100.0


def _beds_compatible(a: Listing, b: Listing) -> bool:
    if a.bedrooms is None or b.bedrooms is None:
        return True
    return a.bedrooms == b.bedrooms


def is_duplicate(a: Listing, b: Listing, cfg: dict) -> bool:
    if a.uid == b.uid or a.accommodation != b.accommodation:
        return False
    if not _beds_compatible(a, b):
        return False
    if a.source == b.source:
        return (
            normalise_address(a.address) == normalise_address(b.address) != ""
            and a.rent_monthly_eur == b.rent_monthly_eur
            and a.bedrooms == b.bedrooms
            and normalise_address(a.title) == normalise_address(b.title)
        )
    if not _price_close(a.rent_monthly_eur, b.rent_monthly_eur, cfg.get("price_tolerance_pct", 4.0)):
        return False
    precise = (
        a.latitude is not None and b.latitude is not None
        and not a.coords_approximate and not b.coords_approximate
    )
    if precise:
        dist_m = haversine_km(a.latitude, a.longitude, b.latitude, b.longitude) * 1000
        if dist_m <= cfg.get("max_distance_m", 120):
            return True
        if dist_m > 1000:
            return False
    return address_similarity(a.address, b.address) >= cfg.get("address_similarity", 0.82)


def find_duplicates(listings: list[Listing], cfg: dict) -> int:
    """Group duplicates in place. Returns the number of groups found.

    The best listing of each group (highest score, then most information)
    becomes the primary; the others get ``extra['_duplicate_secondary']``.
    """
    parent = list(range(len(listings)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(listings)):
        for j in range(i + 1, len(listings)):
            if is_duplicate(listings[i], listings[j], cfg):
                ri, rj = find(i), find(j)
                if ri != rj:
                    parent[rj] = ri

    groups: dict[int, list[Listing]] = {}
    for i, lst in enumerate(listings):
        groups.setdefault(find(i), []).append(lst)

    n = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        n += 1
        gid = hashlib.sha1("|".join(sorted(m.uid for m in members)).encode()).hexdigest()[:10]

        def info(m: Listing) -> tuple:
            return (
                m.score if m.score is not None else -1,
                bool(m.description),
                not m.coords_approximate,
                -(m.rent_monthly_eur or 0),
            )

        members.sort(key=info, reverse=True)
        primary = members[0]
        for m in members:
            m.duplicate_group = gid
            m.duplicate_urls = [o.url for o in members if o is not m]
            if m is not primary:
                m.extra["_duplicate_secondary"] = True
            else:
                m.extra.pop("_duplicate_secondary", None)
        sources = sorted({m.source for m in members})
        if len(sources) > 1:
            primary.notes.append("Also advertised on: " + ", ".join(s for s in sources if s != primary.source))
        else:
            primary.notes.append(f"{len(members)} near-identical adverts merged")
    return n
