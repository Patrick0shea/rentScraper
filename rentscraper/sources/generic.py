"""Property.ie, Rent.ie and RoomsForRent.ie.

Property.ie and Rent.ie (both owned by the Daft group) serve a Cloudflare
challenge to automated clients, and RoomsForRent.ie was unreachable when this
project was built. These sources make ordinary robots.txt-checked requests,
report ``blocked``/``unreachable`` when that happens and never try to get
around it. If pages do load, listings are read from schema.org JSON-LD where
present, or from the long-standing ``.search_result`` card markup.
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from ..http import BlockedError, RobotsDisallowedError, ScrapeError
from ..models import ENTIRE, SHARED, Listing, stable_id
from ..parsing import clean_text, parse_bedrooms, parse_int, parse_monthly_price
from .base import Source

LD_TYPES = {"Offer", "Residence", "Apartment", "House", "SingleFamilyResidence", "Accommodation", "Room", "Product"}


def _iter_ld(html: str) -> Iterable[dict]:
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', html, re.S):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            cur = stack.pop()
            if isinstance(cur, list):
                stack.extend(cur)
            elif isinstance(cur, dict):
                yield cur
                for key in ("@graph", "itemListElement", "item", "mainEntity"):
                    if key in cur:
                        stack.append(cur[key])


def _baths(text: Optional[str]) -> Optional[int]:
    m = re.search(r"(\d+)\s*bath", text or "", re.I)
    return int(m.group(1)) if m else None


def parse_listing_page(html: str, base_url: str, source: str, now: str) -> list[Listing]:
    out: dict[str, Listing] = {}
    # 1) JSON-LD
    for item in _iter_ld(html):
        types = item.get("@type")
        types = set(types) if isinstance(types, list) else {types}
        if not types & LD_TYPES:
            continue
        offers = item.get("offers") if isinstance(item.get("offers"), dict) else item
        url = item.get("url") or offers.get("url")
        name = clean_text(item.get("name"))
        if not url or not name:
            continue
        price = offers.get("price")
        price_text = f"€{price} per month" if price not in (None, "") else None
        addr = item.get("address")
        if isinstance(addr, dict):
            addr = ", ".join(str(v) for k, v in addr.items() if not k.startswith("@") and v)
        url = urljoin(base_url, url)
        out[url] = Listing(
            source=source,
            source_id=stable_id(url),
            url=url,
            title=name,
            address=clean_text(addr) or name,
            rent_monthly_eur=parse_monthly_price(price_text),
            rent_text=price_text,
            bedrooms=parse_int(item.get("numberOfRooms") or item.get("numberOfBedrooms")),
            accommodation=ENTIRE,
            date_scraped=now,
        )
    if out:
        return list(out.values())
    # 2) Classic Property.ie / Rent.ie markup
    soup = BeautifulSoup(html, "lxml")
    for card in soup.select(".search_result, .sresult"):
        link = card.select_one(".sresult_address a, h2 a, a[href]")
        if not link or not link.get("href"):
            continue
        url = urljoin(base_url, link["href"])
        title = clean_text(link.get_text(" ", strip=True)) or ""
        price_el = card.select_one(".sresult_description h3, .price, h3")
        price_text = clean_text(price_el.get_text(" ", strip=True)) if price_el else None
        beds_el = card.select_one(".sresult_description h4, h4")
        beds_text = clean_text(beds_el.get_text(" ", strip=True)) if beds_el else None
        out[url] = Listing(
            source=source,
            source_id=stable_id(url),
            url=url,
            title=title,
            address=title,
            rent_monthly_eur=parse_monthly_price(price_text),
            rent_text=price_text,
            bedrooms=parse_bedrooms(beds_text),
            bathrooms=_baths(beds_text),
            accommodation=SHARED if re.search(r"\b(room|share|sharing|house ?share)\b", title, re.I) else ENTIRE,
            date_scraped=now,
        )
    return list(out.values())


class GenericListingSource(Source):
    def scrape(self) -> None:
        seen: dict[str, Listing] = {}
        for path in self.cfg.get("search_paths", ["/"]):
            url = self.url(path)
            try:
                html = self.fetch(url)
            except (BlockedError, RobotsDisallowedError):
                raise
            except ScrapeError as exc:
                if self.result.pages_fetched == 0:
                    raise
                self.page_failed(url, exc)
                continue
            self.result.pages_fetched += 1
            for lst in parse_listing_page(html, self.base_url, self.name, self.now):
                seen.setdefault(lst.source_id, lst)
        self.result.listings = list(seen.values())
        if not seen:
            self.result.message = "pages fetched but no listings recognised"


class PropertyIeSource(GenericListingSource):
    name = "propertyie"
    display_name = "Property.ie"
    base_url = "https://www.property.ie"


class RentIeSource(GenericListingSource):
    name = "rentie"
    display_name = "Rent.ie"
    base_url = "https://www.rent.ie"


class RoomsForRentSource(GenericListingSource):
    name = "roomsforrent"
    display_name = "RoomsForRent.ie"
    base_url = "https://www.roomsforrent.ie"
