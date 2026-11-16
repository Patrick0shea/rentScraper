"""HousingAnywhere scraper.

HousingAnywhere is a mid-term rental marketplace. The search page
server-renders listing cards (``data-test-locator="ListingCard"``); detail
pages carry schema.org ``Accommodation`` JSON-LD with coordinates.
robots.txt disallows ``/api/*`` (so the internal API is NOT used) and
``/<lang>/s/*?*``; the English ``/s/Dublin--Ireland?page=N`` path is allowed
and is checked against robots.txt at runtime anyway.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

from bs4 import BeautifulSoup

from ..http import BlockedError, RobotsDisallowedError, ScrapeError
from ..models import ENTIRE, SHARED, Listing
from ..parsing import clean_text, parse_bedrooms, parse_date, parse_monthly_price
from .base import PARTIAL, Source

ID_RE = re.compile(r"/room/(ut\d+|\d+)")


def _text(card, locator: str) -> Optional[str]:
    el = card.find(attrs={"data-test-locator": locator})
    return clean_text(el.get_text(" ", strip=True)) if el else None


def classify_title(title: str) -> tuple[str, str]:
    """Return (accommodation, property_type) from a card title."""
    t = title.lower()
    if t.startswith("shared room"):
        return SHARED, "Shared room"
    if t.startswith("private room") or t.startswith("room"):
        return SHARED, "Private room"
    if t.startswith("studio"):
        return ENTIRE, "Studio"
    if t.startswith("apartment"):
        return ENTIRE, "Apartment"
    if t.startswith("house"):
        return ENTIRE, "House"
    m = re.match(r"([A-Za-z ]+?)\s+in\s", title)
    return ENTIRE if m else "unknown", (m.group(1) if m else "Unknown")


def parse_search_page(html: str) -> list[dict]:
    soup = BeautifulSoup(html, "lxml")
    out = []
    for anchor in soup.find_all("a", attrs={"data-test-locator": "ListingCard/Anchor"}):
        href = anchor.get("href") or ""
        card = anchor.find(attrs={"data-test-locator": "ListingCard"}) or anchor
        m = ID_RE.search(href)
        if not m:
            continue
        out.append(
            {
                "id": m.group(1),
                "url": href if href.startswith("http") else "https://housinganywhere.com" + href,
                "title": _text(card, "ListingCard/Title"),
                "price": _text(card, "ListingCard/Price"),
                "price_label": _text(card, "ListingCard/PriceLabel"),
                "availability": _text(card, "ListingCard/Availability"),
                "size": _text(card, "ListingCard/AttributesSize"),
                "places": _text(card, "ListingCard/AttributesPlaces"),
            }
        )
    return out


PAGE_INFO_RE = re.compile(r'"pageInfo"\s*:\s*\{[^{}]*?"pages"\s*:\s*(\d+)')


def parse_page_count(html: str) -> Optional[int]:
    """Number of result pages, from the embedded search state (if present)."""
    m = PAGE_INFO_RE.search(html)
    return int(m.group(1)) if m else None


def listing_from_card(c: dict, now: str) -> Optional[Listing]:
    title = c.get("title") or ""
    if not title:
        return None
    accommodation, ptype = classify_title(title)
    price_text = " ".join(p for p in (c.get("price"), c.get("price_label")) if p)
    available_from = None
    if c.get("availability"):
        d = parse_date(re.sub(r"(?i)available\s+(from)?", "", c["availability"]))
        available_from = d.isoformat() if d else None
    address = None
    m = re.search(r"\bin\s+(.+)$", title)
    if m:
        address = clean_text(m.group(1))
    beds = parse_bedrooms(c.get("places"))
    if ptype == "Studio":
        beds = 0
    return Listing(
        source="housinganywhere",
        source_id=c["id"],
        url=c["url"],
        title=title,
        rent_monthly_eur=parse_monthly_price(price_text),
        rent_text=price_text or None,
        address=address,
        bedrooms=beds,
        property_type=ptype,
        accommodation=accommodation,
        available_from=available_from,
        date_scraped=now,
        extra={"size": c.get("size"), "availability_text": c.get("availability")},
    )


def parse_detail_page(html: str) -> dict[str, Any]:
    info: dict[str, Any] = {}
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        items = data.get("@graph", [data]) if isinstance(data, dict) else data
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or item.get("@type") not in ("Accommodation", "Apartment", "House", "Room", "Residence"):
                continue
            geo = item.get("geo") or {}
            try:
                info["latitude"] = float(geo["latitude"])
                info["longitude"] = float(geo["longitude"])
            except (KeyError, TypeError, ValueError):
                pass
            if item.get("description"):
                info["description"] = clean_text(item["description"])
            if item.get("numberOfRooms") not in (None, ""):
                info["number_of_rooms"] = item["numberOfRooms"]
    # Minimum / maximum stay statements, when present in the page text.
    text = BeautifulSoup(html, "lxml").get_text(" ", strip=True)
    m = re.search(r"(?i)minimum (?:stay|rental period)[^.]{0,40}?(\d+)\s*(month|week|day)", text)
    if m:
        info["minimum_stay"] = f"{m.group(1)} {m.group(2)}s"
    return info


class HousingAnywhereSource(Source):
    name = "housinganywhere"
    display_name = "HousingAnywhere"
    base_url = "https://housinganywhere.com"

    def scrape(self) -> None:
        path = self.cfg.get("search_path", "/s/Dublin--Ireland")
        max_pages = int(self.cfg.get("max_pages", 10))
        seen: dict[str, Listing] = {}
        hit_cap = True
        pages_total: Optional[int] = None
        for page in range(1, max_pages + 1):
            url = self.url(path) + (f"?page={page}" if page > 1 else "")
            try:
                html = self.fetch(url)
                cards = parse_search_page(html)
            except (BlockedError, RobotsDisallowedError):
                raise
            except ScrapeError as exc:
                if self.result.pages_fetched == 0:
                    raise
                self.page_failed(url, exc)
                hit_cap = False
                break
            self.result.pages_fetched += 1
            new = 0
            for c in cards:
                lst = listing_from_card(c, self.now)
                if lst and lst.source_id not in seen:
                    seen[lst.source_id] = lst
                    new += 1
            pages_total = parse_page_count(html) or pages_total
            self.log.info("page %d/%s: %d cards (%d new)", page, pages_total or "?", len(cards), new)
            if not cards or new == 0 or (pages_total and page >= pages_total):
                hit_cap = False
                break
        if hit_cap:
            # Page cap reached while pages still had new results.
            self.result.status = PARTIAL
            self.result.errors.append(f"stopped at page cap {max_pages}")
        listings = list(seen.values())
        if self.cfg.get("fetch_details", True):
            self._fetch_details(listings)
        self.result.listings = listings

    def _fetch_details(self, listings: list[Listing]) -> None:
        cap = int(self.cfg.get("max_detail_pages", 40))
        candidates = [l for l in listings if self.is_candidate(l)]
        for lst in candidates[:cap]:
            try:
                info = parse_detail_page(self.fetch(lst.url))
            except (BlockedError, ScrapeError) as exc:
                self.log.warning("detail page failed %s: %s", lst.url, exc)
                self.result.errors.append(f"detail {lst.url}: {exc}")
                continue
            self.result.detail_pages_fetched += 1
            if "latitude" in info:
                lst.latitude, lst.longitude = info["latitude"], info["longitude"]
            if info.get("description"):
                lst.description = info["description"]
            if info.get("minimum_stay"):
                lst.extra["minimum_stay"] = info["minimum_stay"]
