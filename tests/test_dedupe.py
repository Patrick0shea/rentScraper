from rentscraper.dedupe import address_similarity, find_duplicates, is_duplicate, normalise_address
from rentscraper.models import ENTIRE, Listing

CFG = {"max_distance_m": 120, "price_tolerance_pct": 4.0, "address_similarity": 0.82}


def L(source, sid, price, beds, address, lat=None, lon=None, title=None, score=50):
    return Listing(source=source, source_id=sid, url=f"https://{source}.test/{sid}", title=title or address,
                   rent_monthly_eur=price, bedrooms=beds, address=address, latitude=lat, longitude=lon,
                   accommodation=ENTIRE, score=score)


def test_normalise_address():
    assert normalise_address("Apt 4, 57 Pembroke Rd., Dublin 4, D04 YRV1") == normalise_address("Apartment 4, 57 Pembroke Road, Dublin 4 D04")


def test_cross_source_same_coordinates():
    a = L("myhome", "1", 2800, 3, "Gordon Street, Grand Canal Dk, Dublin 4", 53.3400, -6.2380)
    b = L("spotahome", "9", 2850, 3, "Gordon St, D04", 53.3401, -6.2381)
    assert is_duplicate(a, b, CFG)


def test_cross_source_address_match_without_coords():
    a = L("myhome", "1", 2800, 3, "12 Test Terrace, Sandymount, Dublin 4")
    b = L("propertyie", "x", 2800, 3, "12 Test Terrace, Sandymount, Dublin 4, D04")
    assert address_similarity(a.address, b.address) > 0.82
    assert is_duplicate(a, b, CFG)


def test_not_duplicate_when_beds_or_price_differ():
    a = L("myhome", "1", 2800, 3, "Gordon Street, Dublin 4", 53.34, -6.238)
    assert not is_duplicate(a, L("daft", "2", 2800, 2, "Gordon Street, Dublin 4", 53.34, -6.238), CFG)
    assert not is_duplicate(a, L("daft", "3", 3400, 3, "Gordon Street, Dublin 4", 53.34, -6.238), CFG)


def test_far_apart_not_duplicate_even_with_similar_name():
    a = L("myhome", "1", 2800, 3, "Main Street, Dublin", 53.34, -6.238)
    b = L("daft", "2", 2800, 3, "Main Street, Dublin", 53.29, -6.30)
    assert not is_duplicate(a, b, CFG)


def test_same_source_distinct_units_kept():
    a = L("myhome", "1", 3260, 2, "Lime House, Glass Bottle Ave, Dublin 4", 53.33, -6.22, title="2 beds – Lime House")
    b = L("myhome", "2", 3450, 2, "Lime House, Glass Bottle Ave, Dublin 4", 53.33, -6.22, title="2 beds – Lime House")
    assert not is_duplicate(a, b, CFG)


def test_same_source_exact_repost_merged():
    a = L("spotahome", "1", 2100, 2, "Test Way, D18", 53.27, -6.2)
    b = L("spotahome", "2", 2100, 2, "Test Way, D18", 53.27, -6.2)
    assert is_duplicate(a, b, CFG)


def test_find_duplicates_marks_primary_and_secondary():
    a = L("myhome", "1", 2800, 3, "Gordon Street, Dublin 4", 53.3400, -6.2380, score=70)
    b = L("spotahome", "9", 2850, 3, "Gordon St, Dublin 4", 53.3401, -6.2381, score=60)
    c = L("myhome", "5", 1500, 1, "Elsewhere", 53.36, -6.26)
    assert find_duplicates([a, b, c], CFG) == 1
    assert a.duplicate_group == b.duplicate_group is not None
    assert "_duplicate_secondary" not in a.extra and b.extra["_duplicate_secondary"]
    assert a.duplicate_urls == [b.url]
    assert c.duplicate_group is None
