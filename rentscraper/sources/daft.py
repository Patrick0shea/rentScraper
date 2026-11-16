"""Daft.ie (and Let.ie, which now redirects to Daft.ie).

Daft.ie sits behind a Cloudflare managed challenge for automated clients. This
scraper makes ordinary, robots.txt-checked requests; if a challenge is served
it reports the source as ``blocked`` and moves on. It never attempts to solve
or evade the challenge. Should the public pages become reachable (e.g. from a
different network), listings are parsed from the page's ``__NEXT_DATA__``
JSON.

Daft's official partner API requires an API key issued by Daft; it is not used.
"""
from __future__ import annotations

import json
import re
from typing import Optional

from ..http import BlockedError, RobotsDisallowedError, ScrapeError
from ..models import ENTIRE, SHARED, Listing
from ..parsing import clean_text, parse_bedrooms, parse_int, parse_monthly_price
from .base import Source

NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', re.S)
PAGE_SIZE = 20


def parse_search_page(html: str) -> tuple[list[dict], int]:
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ValueError("__NEXT_DATA__ not found")
    data = json.loads(m.group(1))
    props = (data.get("props") or {}).get("pageProps") or {}
    raw = props.get("listings") or []
    out = []
    for item in raw:
        lst = item.get("listing", item) if isinstance(item, dict) else None
        if isinstance(lst, dict):
            out.append(lst)
    paging = props.get("paging") or {}
    total = int(paging.get("totalResults") or len(out))
    return out, total


def listing_from_daft(d: dict, now: str) -> Optional[Listing]:
    lid = d.get("id")
    path = d.get("seoFriendlyPath")
    if not lid or not path:
        return None
    price_text = clean_text(d.get("price"))
    coords = (d.get("point") or {}).get("coordinates") or []
    lat = lon = None
    if isinstance(coords, list) and len(coords) == 2:
        lon, lat = float(coords[0]), float(coords[1])
    is_share = "/share/" in path or (d.get("sections") and "Sharing" in d.get("sections", []))
    ptype = clean_text(d.get("propertyType"))
    return Listing(
        source="daft",
        source_id=str(lid),
        url="https://www.daft.ie" + path,
        title=clean_text(d.get("title")) or "",
        address=clean_text(d.get("title")),
        rent_monthly_eur=parse_monthly_price(price_text),
        rent_text=price_text,
        bedrooms=parse_bedrooms(d.get("numBedrooms")),
        bathrooms=parse_int(d.get("numBathrooms")),
        property_type=ptype,
        accommodation=SHARED if is_share else ENTIRE,
        latitude=lat,
        longitude=lon,
        date_scraped=now,
    )


class DaftSource(Source):
    name = "daft"
    display_name = "Daft.ie"
    base_url = "https://www.daft.ie"

    def scrape(self) -> None:
        seen: dict[str, Listing] = {}
        max_pages = int(self.cfg.get("max_pages_per_search", 5))
        for path in self.cfg.get("search_paths", []):
            for page in range(max_pages):
                url = self.url(path) + (f"?from={page * PAGE_SIZE}&pageSize={PAGE_SIZE}" if page else "")
                try:
                    raw, total = parse_search_page(self.fetch(url))
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
                for d in raw:
                    lst = listing_from_daft(d, self.now)
                    if lst and lst.source_id not in seen:
                        seen[lst.source_id] = lst
                if (page + 1) * PAGE_SIZE >= total:
                    break
        self.result.listings = list(seen.values())


class LetIeSource(Source):
    """Let.ie redirects to Daft.ie; this just records that fact each run."""

    name = "letie"
    display_name = "Let.ie"
    base_url = "https://www.let.ie"

    def scrape(self) -> None:
        resp = self.session.get(self.url("/"), check_robots=False)
        self.result.pages_fetched += 1
        final = resp.url
        if "daft.ie" in final:
            self.result.message = "Let.ie redirects to Daft.ie; listings are covered by the daft source"
        else:
            self.result.message = f"Let.ie reachable at {final}; no parser for its current layout"
