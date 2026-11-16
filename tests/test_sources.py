import json

from rentscraper.http import PoliteSession
from rentscraper.models import ENTIRE, SHARED
from rentscraper.sources import daft, generic, housinganywhere, myhome, spotahome
from rentscraper.sources.base import BLOCKED, OK, PARTIAL, UNREACHABLE

from . import fixtures as fx

NOW = "2026-11-16T00:00:00+00:00"
SEARCH = {"max_total_monthly_rent_eur": 3000, "max_per_person_monthly_eur": 1000}


def session(routes):
    return PoliteSession("rentscraper-test/1.0", min_delay=0, jitter=0, backoff=0, session=fx.FakeHTTP(routes), sleep=lambda s: None)


# --- MyHome -------------------------------------------------------------------

def test_myhome_parse_search_page():
    html = fx.myhome_search_html([
        fx.myhome_result(1, 3, 2900, "1 Test Road, Ballsbridge, Dublin 4", 53.33, -6.23),
        fx.myhome_result(2, 2, 2400, "2 Test Quay, Ringsend, Dublin 4"),
    ], total=41)
    results, total, size = myhome.parse_search_page(html)
    assert (len(results), total, size) == (2, 41, 20)
    l = myhome.listing_from_result(results[0], "https://www.myhome.ie", NOW)
    assert l.source_id == "1" and l.rent_monthly_eur == 2900 and l.bedrooms == 3
    assert l.latitude == 53.33 and l.accommodation == ENTIRE
    assert l.url == "https://www.myhome.ie/rentals/brochure/test-1/1"
    assert l.listed_on == "2026-11-10"


def test_myhome_brochure():
    info = myhome.parse_brochure(fx.myhome_brochure_html("Minimum 12 month lease.", "D04 TEST"))
    assert info["description"] == "Minimum 12 month lease."
    assert info["eircode"] == "D04 TEST" and info["features"] == ["Balcony", "Parking"]


def test_myhome_source_paginates_and_fetches_details():
    base = "https://www.myhome.ie"
    path = "/rentals/dublin/property-to-rent-in-dublin-4"
    page1 = [fx.myhome_result(i, 3, 2500 + i, f"{i} Test Road, Dublin 4") for i in range(1, 21)]
    page2 = [fx.myhome_result(100, 2, 2200, "100 Test Road, Dublin 4")]
    routes = {
        base + "/robots.txt": (200, "User-agent: *\nAllow: /rentals/*?page=\nDisallow: /rentals/*?\n"),
        base + path: (200, fx.myhome_search_html(page1, total=21)),
        base + path + "?page=2": (200, fx.myhome_search_html(page2, total=21)),
    }
    for r in page1 + page2:
        routes[base + r["BrochureUrl"]] = (200, fx.myhome_brochure_html("Synthetic description"))
    src = myhome.MyHomeSource(session(routes), {"search_paths": [path], "max_pages_per_search": 5, "max_detail_pages": 3}, SEARCH)
    res = src.run()
    assert res.status == OK
    assert len(res.listings) == 21
    assert res.pages_fetched == 2
    assert res.detail_pages_fetched == 3
    assert sum(1 for l in res.listings if l.description) == 3


def test_myhome_removed_listing_detected_from_redirect():
    base = "https://www.myhome.ie"
    path = "/rentals/dublin/property-to-rent-in-dublin-4"
    r = fx.myhome_result(7, 3, 2500, "7 Test Road, Dublin 4")
    routes = {
        base + "/robots.txt": (404, ""),
        base + path: (200, fx.myhome_search_html([r])),
        base + r["BrochureUrl"]: (200, "<html></html>", {"x-final-url": base + "/rentals/dublin/x#listing-removed"}),
    }
    res = myhome.MyHomeSource(session(routes), {"search_paths": [path]}, SEARCH).run()
    assert res.listings[0].status == "removed_on_site"
    assert not res.errors


def test_myhome_layout_change_is_reported_not_crash():
    base = "https://www.myhome.ie"
    routes = {base + "/robots.txt": (404, ""), base + "/x": (200, "<html>new layout</html>")}
    res = myhome.MyHomeSource(session(routes), {"search_paths": ["/x"], "fetch_details": False}, SEARCH).run()
    assert res.status == PARTIAL and res.errors


# --- Spotahome -------------------------------------------------------------------

def test_turbo_stream_decoder_handles_specials():
    arr = [{"_1": 2, "_3": -5, "_4": 5}, "a", 10, "b", "c", ["N", {"_6": 7}], "d", "e"]
    assert spotahome.decode_turbo_stream(arr) == {"a": 10, "b": None, "c": {"d": "e"}}


def test_turbo_encode_roundtrip():
    value = {"x": [1, 2, {"y": None}], "z": "s"}
    assert spotahome.decode_turbo_stream(fx.turbo_encode(value)) == value


def test_spotahome_parse_and_classify():
    cards = [
        fx.spotahome_card("101", "apartment", 3, 2700, "3-bedroom apartment for rent in Ringsend, Dublin", "Test Street", "D04 AAAA", -6.226, 53.341),
        fx.spotahome_card("102", "room_shared", 4, 850, "Room in shared 4-bedroom flat in Sandymount, Dublin", "Test Lane", "D04 BBBB", -6.218, 53.330),
        fx.spotahome_card("103", "studio", 0, 1500, "Studio for rent in Dublin", "Test Ave", "D02 CCCC", -6.25, 53.34),
    ]
    raw, total = spotahome.parse_search_page(fx.spotahome_search_html(cards, total=3))
    assert total == 3 and len(raw) == 3
    ls = {l.source_id: l for l in (spotahome.listing_from_card(c, "https://www.spotahome.com", NOW) for c in raw)}
    apt, room, studio = ls["101"], ls["102"], ls["103"]
    assert apt.accommodation == ENTIRE and apt.bedrooms == 3 and apt.rent_monthly_eur == 2700
    assert (apt.latitude, apt.longitude) == (53.341, -6.226)
    assert apt.available_from == "2027-01-01"
    assert "Ringsend" in apt.address
    assert room.accommodation == SHARED and room.extra["flat_bedrooms"] == 4
    assert studio.bedrooms == 0
    assert apt.url == "https://www.spotahome.com/dublin/for-rent:apartments/101"


def test_spotahome_residences_and_flatshares_are_shared():
    base = "https://www.spotahome.com"
    cards = [
        fx.spotahome_card("201", "residence", 8, 1180, "Ensuite Rooms in Student Residence in Dublin 1", "S", "D01", -6.26, 53.35),
        fx.spotahome_card("202", "residence", 11, 700, "Bed for rent in a residence in Dublin", "S", "D07", -6.27, 53.36),
        fx.spotahome_card("203", "apartment", 2, 2150, "Stylish 2-bedroom flatshare in North Inner City, Dublin", "S", "D01", -6.25, 53.35),
        fx.spotahome_card("204", "apartment", 3, 2900, "3-bedroom apartment for rent in East Wall, Dublin", "S", "D03", -6.23, 53.355),
    ]
    ls = {c["id"]: spotahome.listing_from_card(c, base, NOW) for c in cards}
    assert ls["201"].accommodation == SHARED
    assert ls["202"].accommodation == SHARED and ls["202"].extra.get("bed_in_shared_room")
    assert ls["203"].accommodation == SHARED
    assert ls["204"].accommodation == ENTIRE


def test_spotahome_source_pagination():
    base = "https://www.spotahome.com"
    p1 = [fx.spotahome_card(str(1000 + i), "apartment", 2, 2000, "2-bedroom flat", "S", "D04", -6.2, 53.3) for i in range(48)]
    p2 = [fx.spotahome_card("2000", "apartment", 3, 2900, "3-bedroom flat", "S", "D04", -6.2, 53.3)]
    routes = {
        base + "/robots.txt": (200, "User-agent: *\nDisallow: /*?budget*\n"),
        base + "/s/dublin--ireland": (200, fx.spotahome_search_html(p1, total=49)),
        base + "/s/dublin--ireland/page:2": (200, fx.spotahome_search_html(p2, total=49)),
    }
    res = spotahome.SpotahomeSource(session(routes), {"search_path": "/s/dublin--ireland", "max_pages": 5}, SEARCH).run()
    assert res.status == OK and len(res.listings) == 49 and res.pages_fetched == 2


# --- HousingAnywhere ---------------------------------------------------------

def test_housinganywhere_cards_and_detail():
    html = fx.ha_search_html([
        fx.ha_card("ut1", "Apartment in Test Road, Dublin", 2600, "3 bedrooms", "Available from 2 January 2027"),
        fx.ha_card("ut2", "Private room in Test Lane, Dublin", 800, "1 bedroom", "Available from 2 March 2027"),
        fx.ha_card("ut3", "Studio in Test Ave, Dublin", 1400, "1 bedroom", "Available now"),
    ])
    cards = housinganywhere.parse_search_page(html)
    ls = [housinganywhere.listing_from_card(c, NOW) for c in cards]
    assert [l.source_id for l in ls] == ["ut1", "ut2", "ut3"]
    assert ls[0].accommodation == ENTIRE and ls[0].bedrooms == 3 and ls[0].rent_monthly_eur == 2600
    assert ls[0].available_from == "2027-01-02" and ls[0].address == "Test Road, Dublin"
    assert ls[1].accommodation == SHARED and ls[1].available_from == "2027-03-02"
    assert ls[2].bedrooms == 0 and ls[2].property_type == "Studio"
    info = housinganywhere.parse_detail_page(fx.ha_detail_html(53.33, -6.23, "Nice place"))
    assert info["latitude"] == 53.33 and info["description"] == "Nice place"
    assert info["minimum_stay"] == "1 months"


def test_housinganywhere_stops_when_no_new_cards():
    base = "https://housinganywhere.com"
    page = fx.ha_search_html([fx.ha_card("ut1", "Apartment in Test Road, Dublin", 2600, "3 bedrooms", "Available from 2 January 2027")], pages=None)
    routes = {
        base + "/robots.txt": (200, "User-agent: *\nDisallow: /api/*\nDisallow: /*/s/*?*\n"),
        base + "/s/Dublin--Ireland": (200, page),
        base + "/s/Dublin--Ireland?page=2": (200, page),
        "https://housinganywhere.com/room/ut1/ie/Dublin/test-street": (200, fx.ha_detail_html(53.33, -6.23, "x")),
    }
    res = housinganywhere.HousingAnywhereSource(session(routes), {"max_pages": 5}, SEARCH).run()
    assert res.status == OK and len(res.listings) == 1 and res.pages_fetched == 2
    assert res.listings[0].latitude == 53.33


# --- Daft / Property.ie / blocked + unreachable ---------------------------------

def test_housinganywhere_uses_page_count():
    base = "https://housinganywhere.com"
    page1 = fx.ha_search_html([fx.ha_card("ut1", "Apartment in A, Dublin", 2600, "3 bedrooms", "Available from 2 January 2027")], pages=2)
    page2 = fx.ha_search_html([fx.ha_card("ut2", "Apartment in B, Dublin", 2500, "2 bedrooms", "Available from 2 January 2027")], pages=2)
    routes = {
        base + "/robots.txt": (404, ""),
        base + "/s/Dublin--Ireland": (200, page1),
        base + "/s/Dublin--Ireland?page=2": (200, page2),
    }
    res = housinganywhere.HousingAnywhereSource(session(routes), {"max_pages": 5, "fetch_details": False}, SEARCH).run()
    assert res.status == OK and res.pages_fetched == 2 and len(res.listings) == 2
    assert housinganywhere.parse_page_count(page1) == 2


def test_daft_next_data_parser():
    html = fx.daft_search_html([
        {"id": 1, "title": "1 Test Road, Ballsbridge, Dublin 4", "seoFriendlyPath": "/for-rent/apartment-1/1",
         "price": "€2,900 per month", "numBedrooms": "3 Bed", "numBathrooms": "2 Bath", "propertyType": "Apartment",
         "point": {"coordinates": [-6.23, 53.33]}},
        {"id": 2, "title": "Room, Test St, Dublin 2", "seoFriendlyPath": "/share/test/2", "price": "€950 per month",
         "numBedrooms": "1 Bed"},
    ])
    raw, total = daft.parse_search_page(html)
    ls = [daft.listing_from_daft(d, NOW) for d in raw]
    assert ls[0].rent_monthly_eur == 2900 and ls[0].bedrooms == 3 and ls[0].latitude == 53.33
    assert ls[1].accommodation == SHARED


def test_daft_blocked_by_cloudflare():
    routes = {"https://www.daft.ie/robots.txt": (403, fx.CLOUDFLARE_CHALLENGE, {"cf-mitigated": "challenge"})}
    res = daft.DaftSource(session(routes), {"search_paths": ["/property-for-rent/dublin-4-dublin"]}, SEARCH).run()
    assert res.status == BLOCKED and res.listings == [] and "challenge" in res.message


def test_propertyie_classic_markup():
    ls = generic.parse_listing_page(fx.propertyie_search_html(), "https://www.property.ie", "propertyie", NOW)
    assert len(ls) == 2
    house = next(l for l in ls if "Terrace" in l.title)
    assert house.rent_monthly_eur == 2850 and house.bedrooms == 3 and house.bathrooms == 2
    room = next(l for l in ls if "room" in l.title.lower())
    assert room.accommodation == SHARED


def test_jsonld_listing_parse():
    ld = {"@context": "https://schema.org", "@graph": [{"@type": "Apartment", "name": "Test Apt", "url": "/a/1",
          "numberOfRooms": 3, "offers": {"@type": "Offer", "price": 2750}, "address": {"streetAddress": "1 Test St", "addressLocality": "Dublin 4"}}]}
    html = f'<script type="application/ld+json">{json.dumps(ld)}</script>'
    ls = generic.parse_listing_page(html, "https://www.rent.ie", "rentie", NOW)
    assert ls[0].rent_monthly_eur == 2750 and ls[0].bedrooms == 3 and ls[0].url == "https://www.rent.ie/a/1"


def test_unreachable_site_reported():
    import requests

    routes = {"https://www.roomsforrent.ie/robots.txt": requests.ConnectionError("502 Bad Gateway")}
    res = generic.RoomsForRentSource(session(routes), {"search_paths": ["/"]}, SEARCH).run()
    assert res.status == UNREACHABLE


def test_letie_redirect_detected():
    routes = {"https://www.let.ie/": (200, "<html>daft</html>", {"x-final-url": "https://www.daft.ie/"})}
    res = daft.LetIeSource(session(routes), {}, SEARCH).run()
    assert res.status == OK and "redirects to Daft.ie" in res.message


def test_unexpected_exception_in_source_does_not_propagate(monkeypatch):
    src = myhome.MyHomeSource(session({}), {"search_paths": ["/x"]}, SEARCH)
    monkeypatch.setattr(src, "scrape", lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    res = src.run()
    assert res.status == "error" and "boom" in res.message
