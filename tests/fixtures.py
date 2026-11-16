"""SYNTHETIC test fixtures.

These pages mimic the *structure* of each site's markup so parsers can be
tested offline. Every address, price and id below is made up for testing
and is never written to real results.
"""
from __future__ import annotations

import json
from typing import Any

import requests
from requests.structures import CaseInsensitiveDict


# --------------------------------------------------------------------------
# MyHome
# --------------------------------------------------------------------------

def myhome_result(pid: int, beds: int, price: int, address: str, lat=None, lon=None, ptype="Apartment") -> dict:
    r = {
        "PropertyId": pid,
        "BrochureUrl": f"/rentals/brochure/test-{pid}/{pid}",
        "PropertyClass": "LettingsToRent",
        "PropertyType": ptype,
        "NumberOfBeds": beds,
        "BedsString": f"{beds} beds",
        "NumberOfBathrooms": 1,
        "BathString": "1 bath",
        "PriceAsString": f"€{price:,} / month",
        "DisplayAddress": address,
        "ActivatedOn": "2026-11-10T10:00:00.0000000+00:00",
        "GroupName": "Test Agent",
        "IsPrivateLandlord": False,
    }
    if lat is not None:
        r["BrochureMap"] = {"latitude": lat, "longitude": lon}
    return r


def myhome_search_html(results: list[dict], total: int | None = None, path="/rentals/dublin/property-to-rent-in-dublin-4") -> str:
    state = {
        "featureFlags": {},
        f"SEARCH_RESOLVER:{path}": {
            "SearchResults": results,
            "ResultCount": total if total is not None else len(results),
            "PageSize": 20,
            "Page": 1,
        },
    }
    return f'<html><body><script id="ng-state" type="application/json">{json.dumps(state)}</script></body></html>'


def myhome_brochure_html(description: str, eircode: str = "") -> str:
    state = {
        "BROCHURE_RESOLVER:/rentals/brochure/x/1": {
            "Brochure": {
                "Property": {
                    "BrochureContent": [{"ContentType": "Description", "Content": description}],
                    "Eircode": eircode,
                    "LocalityName": "Ballsbridge",
                    "RegionName": "Dublin 4",
                    "PropertyType": "Apartment",
                    "Bathrooms": 2,
                },
                "Features": ["Balcony", "Parking"],
                "LatestPriceChangeString": "",
            }
        }
    }
    return f'<html><script id="ng-state" type="application/json">{json.dumps(state)}</script></html>'


# --------------------------------------------------------------------------
# Spotahome (turbo-stream)
# --------------------------------------------------------------------------

def turbo_encode(value: Any) -> list:
    """Minimal turbo-stream encoder (inverse of the decoder) for tests."""
    arr: list = []
    str_index: dict[str, int] = {}

    def enc(v: Any) -> int:
        if v is None:
            return -5
        if isinstance(v, str):
            if v in str_index:
                return str_index[v]
            arr.append(v)
            str_index[v] = len(arr) - 1
            return len(arr) - 1
        if isinstance(v, (bool, int, float)):
            arr.append(v)
            return len(arr) - 1
        idx = len(arr)
        arr.append(None)
        if isinstance(v, dict):
            obj = {}
            for k, val in v.items():
                obj[f"_{enc(k)}"] = enc(val)
            arr[idx] = obj
        elif isinstance(v, list):
            arr[idx] = [enc(x) for x in v]
        return idx

    enc(value)
    return arr


def spotahome_card(cid: str, ctype: str, beds: int, price: int, title: str, street: str, postal: str,
                   lon: float, lat: float, avail: str = "2027-01-01T00:00:00+0000") -> dict:
    return {
        "id": cid,
        "adId": int(cid) - 1,
        "url": f"/dublin/for-rent:{'rooms' if ctype.startswith('room') else 'apartments'}/{cid}",
        "type": ctype,
        "title": title,
        "description": f"Synthetic description for {title}.",
        "numberOfBedrooms": beds,
        "numberOfBathrooms": 1,
        "displayPrice": str(price),
        "firstAvailableDate": avail,
        "location": {"street": street, "postalCode": postal, "city": "Dublin", "coord": [lon, lat]},
        "billsIncluded": False,
        "checked": True,
    }


def spotahome_search_html(cards: list[dict], total: int | None = None) -> str:
    root = {
        "loaderData": {
            "root": {"x": 1},
            "marketplace-search": {
                "initialHomecards": {c["id"]: c for c in cards},
                "paginatedCount": total if total is not None else len(cards),
                "cityListingCount": total if total is not None else len(cards),
            },
        },
        "actionData": None,
        "errors": None,
    }
    payload = json.dumps(turbo_encode(root))
    return (
        "<html><body><script>window.__reactRouterContext.streamController.enqueue("
        + json.dumps(payload)
        + ");</script></body></html>"
    )


# --------------------------------------------------------------------------
# HousingAnywhere
# --------------------------------------------------------------------------

def ha_card(uid: str, title: str, price: int, places: str, availability: str, slug="test-street") -> str:
    return f"""
<a href="https://housinganywhere.com/room/{uid}/ie/Dublin/{slug}" data-test-locator="ListingCard/Anchor">
 <div data-test-locator="ListingCard">
  <div data-test-locator="ListingCard/Title">{title}</div>
  <span data-test-locator="ListingCard/Price">€{price}</span>
  <span data-test-locator="ListingCard/PriceLabel">/month, incl. some utilities</span>
  <div data-test-locator="ListingCard/Availability">{availability}</div>
  <div data-test-locator="ListingCard/AttributesSize">70 m²</div>
  <div data-test-locator="ListingCard/AttributesPlaces">{places}</div>
 </div>
</a>"""


def ha_search_html(cards: list[str], pages: int | None = 1) -> str:
    state = "" if pages is None else (
        '<script>window.__PRELOADED_STATE__ = ({"search":{"pageInfo":{"offset":0,"total":%d,"pages":%d,"limit":23}}});</script>'
        % (len(cards), pages)
    )
    return "<html><body>" + state + "<div>" + "".join(cards) + "</div></body></html>"


def ha_detail_html(lat: float, lon: float, description: str) -> str:
    ld = {
        "@context": "http://schema.org",
        "@type": "Accommodation",
        "name": "Apartment for rent",
        "description": description,
        "numberOfRooms": "3",
        "geo": {"@type": "GeoCoordinates", "latitude": str(lat), "longitude": str(lon)},
    }
    return f'<html><head><script type="application/ld+json">{json.dumps(ld)}</script></head><body>Minimum stay 1 month</body></html>'


# --------------------------------------------------------------------------
# Daft / Property.ie
# --------------------------------------------------------------------------

def daft_search_html(listings: list[dict], total: int | None = None) -> str:
    data = {"props": {"pageProps": {"listings": [{"listing": l} for l in listings],
                                    "paging": {"totalResults": total if total is not None else len(listings)}}}}
    return f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script></html>'


def propertyie_search_html() -> str:
    return """
<div class="search_result">
  <div class="sresult_address"><h2><a href="/property-to-let/12-test-terrace-sandymount-dublin-4/999/">12 Test Terrace, Sandymount, Dublin 4</a></h2></div>
  <div class="sresult_description"><h3>€2,850 monthly</h3><h4>3 Bedrooms, 2 Bathrooms, House</h4></div>
</div>
<div class="search_result">
  <div class="sresult_address"><h2><a href="/property-to-let/room-test/1000/">Double room to rent, Test Road, Dublin 2</a></h2></div>
  <div class="sresult_description"><h3>€950 monthly</h3><h4>1 Bedroom</h4></div>
</div>"""


CLOUDFLARE_CHALLENGE = "<html><head><title>Just a moment...</title></head><body><div id='cf-browser-verification'>challenge-platform</div></body></html>"

PERMISSIVE_ROBOTS = "User-agent: *\nDisallow: /private/\n"


# --------------------------------------------------------------------------
# Fake HTTP
# --------------------------------------------------------------------------

class FakeHTTP:
    """Stands in for ``requests.Session``: url -> (status, body, headers) or Exception."""

    def __init__(self, routes: dict[str, Any]):
        self.routes = routes
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []

    def get(self, url: str, timeout: float = 0, allow_redirects: bool = True) -> requests.Response:
        self.calls.append(url)
        route = self.routes.get(url)
        if route is None:
            route = (404, "not found", {})
        if isinstance(route, Exception):
            raise route
        if callable(route):
            route = route()
        status, body, headers = route if len(route) == 3 else (*route, {})
        r = requests.Response()
        r.status_code = status
        r._content = body.encode("utf-8")
        r.headers = CaseInsensitiveDict(headers)
        r.url = headers.get("x-final-url", url)
        r.encoding = "utf-8"
        return r
