"""Geography helpers: distances and Dublin area detection."""
from __future__ import annotations

import math
import re
from typing import Iterable, Optional

# Approximate centroids, used ONLY when a source gives no coordinates.
# Listings positioned this way are marked ``coords_approximate``.
AREA_CENTROIDS: dict[str, tuple[float, float]] = {
    "ballsbridge": (53.3290, -6.2300),
    "donnybrook": (53.3220, -6.2370),
    "sandymount": (53.3300, -6.2180),
    "ringsend": (53.3410, -6.2260),
    "irishtown": (53.3380, -6.2210),
    "grand canal dock": (53.3395, -6.2380),
    "grand canal dk": (53.3395, -6.2380),
    "docklands": (53.3470, -6.2400),
    "spencer dock": (53.3490, -6.2380),
    "ifsc": (53.3495, -6.2470),
    "north wall": (53.3490, -6.2330),
    "east wall": (53.3550, -6.2300),
    "pearse street": (53.3433, -6.2470),
    "pearse st": (53.3433, -6.2470),
    "dublin 1": (53.3520, -6.2600),
    "dublin 2": (53.3390, -6.2560),
    "dublin 3": (53.3610, -6.2250),
    "dublin 4": (53.3270, -6.2290),
    "dublin 6": (53.3200, -6.2650),
    "dublin 7": (53.3570, -6.2850),
    "dublin 8": (53.3380, -6.2900),
}

_DISTRICT_RE = re.compile(r"\bdublin\s*(\d{1,2}w?)\b|\bD\s?(\d{1,2}W?)\b|\bD(\d{2})\s?[A-Z0-9]{4}\b", re.I)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371.0088
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def dublin_district(text: Optional[str]) -> Optional[str]:
    """Extract 'Dublin 4' style postal district from an address or Eircode."""
    if not text:
        return None
    for m in _DISTRICT_RE.finditer(text):
        num = m.group(1) or m.group(2) or m.group(3)
        if not num:
            continue
        num = num.upper().lstrip("0") or "0"
        if num.endswith("W"):
            return f"Dublin {num[:-1]}W"
        n = int(num)
        if 1 <= n <= 24:
            return f"Dublin {n}"
    return None


def match_area(text: Optional[str], names: Iterable[str]) -> Optional[str]:
    """Return the first configured area name mentioned in the text."""
    if not text:
        return None
    low = text.lower()
    for name in sorted(names, key=len, reverse=True):
        if re.search(r"\b" + re.escape(name.lower()) + r"\b", low):
            return name
    return None


def approximate_coords(text: Optional[str]) -> Optional[tuple[float, float]]:
    if not text:
        return None
    low = text.lower()
    for name in sorted(AREA_CENTROIDS, key=len, reverse=True):
        if name.startswith("dublin "):
            continue
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return AREA_CENTROIDS[name]
    district = dublin_district(text)
    if district and district.lower() in AREA_CENTROIDS:
        return AREA_CENTROIDS[district.lower()]
    return None
