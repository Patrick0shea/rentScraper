import pytest

from rentscraper.geo import approximate_coords, dublin_district, haversine_km, match_area


def test_haversine_known_distance():
    # Dublin Spire -> Trinity College front gate is roughly 0.6 km
    d = haversine_km(53.34981, -6.26031, 53.34444, -6.25917)
    assert 0.5 < d < 0.7


@pytest.mark.parametrize(
    "text,expected",
    [
        ("Lime House, Glass Bottle Ave, Dublin 4, D04 YRV1", "Dublin 4"),
        ("Somewhere, D04 YRV1", "Dublin 4"),
        ("Cedar Brook Ave, D10 C919, Dublin", "Dublin 10"),
        ("Rathmines, Dublin 6W", "Dublin 6W"),
        ("Pearse Street, Dublin 2", "Dublin 2"),
        ("Cork City", None),
        (None, None),
    ],
)
def test_dublin_district(text, expected):
    assert dublin_district(text) == expected


def test_match_area_prefers_longest_and_word_boundaries():
    areas = ["Grand Canal", "Grand Canal Dock", "IFSC", "Ringsend"]
    assert match_area("The Willows, Grand Canal Dock, Dublin 2", areas) == "Grand Canal Dock"
    assert match_area("Custom House Square, IFSC, Dublin 1", areas) == "IFSC"
    assert match_area("Ringsendish Road", areas) is None


def test_approximate_coords_uses_area_then_district():
    assert approximate_coords("Somewhere in Sandymount") is not None
    assert approximate_coords("Apartment, Dublin 4") is not None
    assert approximate_coords("Galway") is None
