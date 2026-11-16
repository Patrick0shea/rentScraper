"""Spotahome scraper.

Spotahome is a mid-term rental platform (1-11+ months), which suits a
January-May let. Search pages are server-rendered with React Router; listing
data ("homecards") is embedded in a turbo-stream payload pushed through
``streamController.enqueue("...")``. Pagination uses clean paths
(``/s/dublin--ireland/page:2``), which robots.txt allows. Query-string
filters such as ``?budget=`` and ``?move-in=`` are disallowed by robots.txt,
so all filtering is done locally.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from ..http import BlockedError, RobotsDisallowedError, ScrapeError
from ..models import ENTIRE, SHARED, Listing
from ..parsing import clean_text, iso_date, parse_monthly_price
from .base import PARTIAL, Source

ENQUEUE_RE = re.compile(r'streamController\.enqueue\(("(?:[^"\\]|\\.)*")\)', re.S)

# turbo-stream constants
_SPECIAL = {-1: None, -2: float("nan"), -3: float("-inf"), -4: 0.0, -5: None, -6: float("inf"), -7: None}

PAGE_SIZE = 48

SHARED_TITLE_RE = re.compile(
    r"\b(flat ?share|house ?share|shared|rooms? in|bed in|bed for rent|ensuite rooms?|student residence)\b", re.I
)


def decode_turbo_stream(arr: list) -> Any:
    """Decode a (v2) turbo-stream flat array into Python objects.

    Objects are encoded as ``{"_<keyIndex>": valueIndex}``, arrays as lists
    of indices, and typed values as ``["<TypeCode>", ...]``.
    """
    memo: dict[int, Any] = {}

    def value(i: Any) -> Any:
        if not isinstance(i, int):
            return i
        if i < 0:
            return _SPECIAL.get(i)
        if i in memo:
            return memo[i]
        x = arr[i]
        if isinstance(x, dict):
            out: dict = {}
            memo[i] = out
            for k, v in x.items():
                key = arr[int(k[1:])] if k.startswith("_") and k[1:].isdigit() else k
                out[str(key)] = value(v)
            return out
        if isinstance(x, list):
            if x and isinstance(x[0], str):
                code = x[0]
                if code == "N" and len(x) > 1 and isinstance(x[1], dict):
                    obj: dict = {}
                    memo[i] = obj
                    for k, v in x[1].items():
                        key = arr[int(k[1:])] if k.startswith("_") and k[1:].isdigit() else k
                        obj[str(key)] = value(v)
                    return obj
                if code == "D" and len(x) > 1:
                    memo[i] = x[1]
                    return x[1]
                memo[i] = None  # promises, symbols, etc. are irrelevant here
                return None
            lst: list = []
            memo[i] = lst
            lst.extend(value(e) for e in x)
            return lst
        memo[i] = x
        return x

    return value(0) if arr else None


def extract_loader_data(html: str) -> dict:
    chunks = ENQUEUE_RE.findall(html)
    if not chunks:
        raise ValueError("turbo-stream payload not found (page layout may have changed)")
    for raw in chunks:
        try:
            payload = json.loads(json.loads(raw))
        except json.JSONDecodeError:
            continue
        decoded = decode_turbo_stream(payload)
        if isinstance(decoded, dict) and isinstance(decoded.get("loaderData"), dict):
            return decoded["loaderData"]
    raise ValueError("loaderData not found in turbo-stream payload")


def parse_search_page(html: str) -> tuple[list[dict], int]:
    loader = extract_loader_data(html)
    search = None
    for key, val in loader.items():
        if isinstance(val, dict) and "initialHomecards" in val:
            search = val
            break
    if search is None:
        raise ValueError("search loader with initialHomecards not found")
    cards = search.get("initialHomecards") or {}
    if isinstance(cards, dict):
        cards = list(cards.values())
    total = int(search.get("paginatedCount") or search.get("cityListingCount") or 0)
    return [c for c in cards if isinstance(c, dict)], total


def listing_from_card(c: dict, base_url: str, now: str) -> Optional[Listing]:
    cid = c.get("id")
    path = c.get("url")
    if not cid or not path:
        return None
    ctype = (c.get("type") or "").lower()
    title = clean_text(c.get("title")) or ""
    price_text = c.get("displayPrice")
    rent = parse_monthly_price(f"€{price_text}") if price_text not in (None, "") else None
    loc = c.get("location") or {}
    coord = loc.get("coord") or []
    lat = lon = None
    if isinstance(coord, list) and len(coord) == 2 and all(isinstance(v, (int, float)) for v in coord):
        lon, lat = float(coord[0]), float(coord[1])
    address_parts = [clean_text(loc.get("street")), clean_text(loc.get("postalCode")), clean_text(loc.get("city"))]
    # The title often names the neighbourhood ("... in Ballsbridge, Dublin").
    neighbourhood = None
    m = re.search(r"\b(?:in|,)\s+([A-Z][\w' .-]+?)(?:,\s*Dublin|\.|$)", title)
    if m:
        neighbourhood = clean_text(m.group(1))
    address = ", ".join(p for p in address_parts if p)
    if neighbourhood and neighbourhood.lower() not in address.lower():
        address = f"{address} ({neighbourhood})" if address else neighbourhood

    # Rooms, beds in student residences and "flatshares" are priced per person.
    shared = ctype.startswith("room") or ctype == "residence" or SHARED_TITLE_RE.search(title)
    accommodation = SHARED if shared else ENTIRE
    beds = c.get("numberOfBedrooms")
    beds = int(beds) if isinstance(beds, (int, float)) else None
    type_label = {
        "apartment": "Apartment",
        "studio": "Studio",
        "room_shared": "Room in shared property",
        "room_private": "Private room",
        "residence": "Residence",
    }.get(ctype, ctype or None)
    extra = {
        "bills_included": c.get("billsIncluded"),
        "capacity": c.get("capacity"),
        "allows_permanent_contract": c.get("allowsPermanentContract"),
        "verified": c.get("checked"),
        "price_is_from": True,
    }
    if accommodation == SHARED:
        extra["flat_bedrooms"] = beds
        if re.search(r"\bbed (?:in|for rent)\b|shared room", title, re.I):
            extra["bed_in_shared_room"] = True
    return Listing(
        source="spotahome",
        source_id=str(cid),
        url=base_url + path,
        title=title or f"{type_label} in Dublin",
        rent_monthly_eur=rent,
        rent_text=f"from €{price_text} / month" if price_text not in (None, "") else None,
        address=address or None,
        bedrooms=0 if ctype == "studio" else beds,
        bathrooms=c.get("numberOfBathrooms") if isinstance(c.get("numberOfBathrooms"), int) else None,
        property_type=type_label,
        description=clean_text(c.get("description")),
        accommodation=accommodation,
        latitude=lat,
        longitude=lon,
        available_from=iso_date(c.get("firstAvailableDate")),
        date_scraped=now,
        extra=extra,
    )


class SpotahomeSource(Source):
    name = "spotahome"
    display_name = "Spotahome"
    base_url = "https://www.spotahome.com"

    def scrape(self) -> None:
        path = self.cfg.get("search_path", "/s/dublin--ireland").rstrip("/")
        max_pages = int(self.cfg.get("max_pages", 20))
        seen: dict[str, Listing] = {}
        pages_needed = 1
        page = 1
        while page <= max_pages:
            url = self.url(path) + (f"/page:{page}" if page > 1 else "")
            try:
                cards, total = parse_search_page(self.fetch(url))
            except (BlockedError, RobotsDisallowedError):
                raise
            except ScrapeError as exc:
                if self.result.pages_fetched == 0:
                    raise
                self.page_failed(url, exc)
                break
            except (ValueError, json.JSONDecodeError) as exc:
                self.page_failed(url, exc)
                break
            self.result.pages_fetched += 1
            new = 0
            for c in cards:
                lst = listing_from_card(c, self.base_url, self.now)
                if lst and lst.source_id not in seen:
                    seen[lst.source_id] = lst
                    new += 1
            pages_needed = max(1, math.ceil(total / PAGE_SIZE)) if total else 1
            self.log.info("page %d/%d: %d cards (%d new)", page, pages_needed, len(cards), new)
            if page >= pages_needed or new == 0:
                break
            page += 1
        if page > max_pages and pages_needed > max_pages:
            self.result.status = PARTIAL
            self.result.errors.append(f"stopped at page cap {max_pages} of {pages_needed}")
        self.result.listings = list(seen.values())
