"""MyHome.ie scraper.

MyHome renders search results server-side and embeds them as JSON in a
``<script id="ng-state">`` element. robots.txt allows the clean search paths
and ``?page=N`` pagination (all other query strings are disallowed, so price
and bedroom filtering is done locally rather than with URL filters).
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from ..models import ENTIRE, SHARED, Listing
from ..parsing import clean_text, iso_date, parse_int, parse_monthly_price
from ..http import BlockedError, RobotsDisallowedError, ScrapeError
from .base import PARTIAL, Source

NG_STATE_RE = re.compile(r'<script id="ng-state" type="application/json">(.*?)</script>', re.S)

SHARED_TYPES = ("share", "room")


def extract_ng_state(html: str) -> dict:
    m = NG_STATE_RE.search(html)
    if not m:
        raise ValueError("ng-state JSON not found (page layout may have changed)")
    return json.loads(m.group(1))


def _resolver(state: dict, prefix: str) -> Optional[dict]:
    for k, v in state.items():
        if k.startswith(prefix) and isinstance(v, dict):
            return v
    return None


def parse_search_page(html: str) -> tuple[list[dict], int, int]:
    """Return (raw result dicts, total result count, page size)."""
    state = extract_ng_state(html)
    res = _resolver(state, "SEARCH_RESOLVER:")
    if res is None:
        raise ValueError("SEARCH_RESOLVER block missing in ng-state")
    results = list(res.get("SearchResults") or [])
    top = res.get("TopSpot")
    if isinstance(top, dict) and top.get("PropertyId"):
        results.append(top)
    return results, int(res.get("ResultCount") or 0), int(res.get("PageSize") or 20)


def listing_from_result(r: dict, base_url: str, now: str) -> Optional[Listing]:
    pid = r.get("PropertyId") or r.get("id")
    path = r.get("BrochureUrl") or r.get("SeoUrl")
    if not pid or not path:
        return None
    if r.get("PropertyClass") and r.get("PropertyClass") != "LettingsToRent":
        return None
    ptype = clean_text(r.get("PropertyType"))
    beds = r.get("NumberOfBeds")
    beds = parse_int(beds) if beds not in (None, "") else parse_int(r.get("BedsString"))
    baths = r.get("NumberOfBathrooms")
    baths = parse_int(baths) if baths not in (None, "") else parse_int(r.get("BathString"))
    price_text = clean_text(r.get("PriceAsString"))
    address = clean_text(r.get("DisplayAddress") or r.get("Address"))
    lat = lon = None
    bmap = r.get("BrochureMap") or {}
    if isinstance(bmap, dict) and bmap.get("latitude") and bmap.get("longitude"):
        lat, lon = float(bmap["latitude"]), float(bmap["longitude"])
    accommodation = ENTIRE
    if ptype and any(t in ptype.lower() for t in SHARED_TYPES):
        accommodation = SHARED
    title_bits = [b for b in (clean_text(r.get("BedsString")), ptype) if b]
    title = (" ".join(title_bits) + " – " if title_bits else "") + (address or "")
    return Listing(
        source="myhome",
        source_id=str(pid),
        url=base_url + path,
        title=title.strip(" –"),
        rent_monthly_eur=parse_monthly_price(price_text),
        rent_text=price_text,
        address=address,
        bedrooms=beds,
        bathrooms=baths,
        property_type=ptype,
        accommodation=accommodation,
        latitude=lat,
        longitude=lon,
        listed_on=iso_date(r.get("ActivatedOn") or r.get("RefreshedOn") or r.get("CreatedOnDate")),
        date_scraped=now,
        extra={
            "agent": clean_text(r.get("GroupName")),
            "private_landlord": r.get("IsPrivateLandlord"),
            "size_m2": r.get("SizeStringMeters"),
            "sale_agreed_or_let": r.get("IsSaleAgreed"),
        },
    )


def parse_brochure(html: str) -> dict[str, Any]:
    """Extract description and extra facts from a brochure (detail) page."""
    state = extract_ng_state(html)
    res = _resolver(state, "BROCHURE_RESOLVER:")
    if res is None:
        raise ValueError("BROCHURE_RESOLVER block missing")
    brochure = res.get("Brochure") or {}
    prop = brochure.get("Property") or {}
    description_parts = []
    for block in prop.get("BrochureContent") or []:
        if isinstance(block, dict) and block.get("Content"):
            description_parts.append(str(block["Content"]).strip())
    features = [clean_text(f) for f in (brochure.get("Features") or []) if isinstance(f, str)]
    return {
        "description": "\n\n".join(description_parts) or None,
        "eircode": clean_text(prop.get("Eircode")),
        "locality": clean_text(prop.get("LocalityName")),
        "region": clean_text(prop.get("RegionName")),
        "property_type": clean_text(prop.get("PropertyType")),
        "bathrooms": prop.get("Bathrooms"),
        "features": [f for f in features if f],
        "price_change": clean_text(brochure.get("LatestPriceChangeString")),
        "expires_on": iso_date(prop.get("ExpiresOn")),
    }


class MyHomeSource(Source):
    name = "myhome"
    display_name = "MyHome.ie"
    base_url = "https://www.myhome.ie"

    def scrape(self) -> None:
        seen: dict[str, Listing] = {}
        max_pages = int(self.cfg.get("max_pages_per_search", 8))
        for path in self.cfg.get("search_paths", []):
            page = 1
            while page <= max_pages:
                url = self.url(path) + (f"?page={page}" if page > 1 else "")
                try:
                    html = self.fetch(url)
                    results, total, size = parse_search_page(html)
                except (BlockedError, RobotsDisallowedError):
                    raise
                except (ValueError, json.JSONDecodeError) as exc:
                    self.page_failed(url, exc)
                    break
                except ScrapeError as exc:
                    if not seen and self.result.pages_fetched == 0:
                        raise
                    self.page_failed(url, exc)
                    break
                self.result.pages_fetched += 1
                for r in results:
                    lst = listing_from_result(r, self.base_url, self.now)
                    if lst and lst.source_id not in seen:
                        seen[lst.source_id] = lst
                pages_needed = math.ceil(total / size) if size else 1
                self.log.info("%s page %d/%d: %d results", path, page, pages_needed, len(results))
                if page >= pages_needed or not results:
                    break
                page += 1
            else:
                self.result.status = PARTIAL
                self.result.errors.append(f"{path}: stopped at page cap {max_pages}")

        listings = list(seen.values())
        if self.cfg.get("fetch_details", True):
            self._fetch_details(listings)
        self.result.listings = listings

    def _fetch_details(self, listings: list[Listing]) -> None:
        cap = int(self.cfg.get("max_detail_pages", 60))
        candidates = [l for l in listings if self.is_candidate(l)]
        candidates.sort(key=lambda l: (-(l.bedrooms or 0), l.rent_monthly_eur or 1e9))
        for i, lst in enumerate(candidates[:cap], 1):
            if i % 10 == 0:
                self.log.info("detail pages: %d/%d", i, min(cap, len(candidates)))
            try:
                resp = self.session.get(lst.url)
                if "listing-removed" in resp.url:
                    # MyHome redirects adverts that were taken down.
                    lst.status = "removed_on_site"
                    lst.notes.append("MyHome says this advert has been removed")
                    self.result.detail_pages_fetched += 1
                    continue
                info = parse_brochure(resp.text)
            except (BlockedError, ScrapeError, ValueError, json.JSONDecodeError) as exc:
                self.log.warning("detail page failed %s: %s", lst.url, exc)
                self.result.errors.append(f"detail {lst.url}: {exc}")
                continue
            self.result.detail_pages_fetched += 1
            lst.description = info["description"]
            if info["eircode"]:
                lst.extra["eircode"] = info["eircode"]
                if lst.address and info["eircode"] not in lst.address:
                    lst.address = f"{lst.address}, {info['eircode']}"
            if info["locality"]:
                lst.extra["locality"] = info["locality"]
            if info["features"]:
                lst.extra["features"] = info["features"]
            if info["price_change"]:
                lst.extra["site_price_change"] = info["price_change"]
            if lst.bathrooms is None and info["bathrooms"] not in (None, ""):
                lst.bathrooms = parse_int(info["bathrooms"])
        if len(candidates) > cap:
            self.log.info("detail cap reached: %d of %d candidates fetched", cap, len(candidates))
