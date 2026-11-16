from datetime import date

import pytest

from rentscraper.parsing import iso_date, parse_bedrooms, parse_date, parse_monthly_price


@pytest.mark.parametrize(
    "text,expected",
    [
        ("€2,200 / month", 2200.0),
        ("€3,000 per month", 3000.0),
        ("2500 € / month", 2500.0),
        ("€1,200 per month (€277 per week)", 1200.0),
        ("€600 per week", round(600 * 52 / 12, 2)),
        ("€950 monthly", 950.0),
        ("€1.250 pcm", 1250.0),
        ("Price on application", None),
        ("€120 per night", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_monthly_price(text, expected):
    assert parse_monthly_price(text) == expected


@pytest.mark.parametrize(
    "text,expected",
    [("3 beds", 3), ("2 Bed", 2), ("1 bedroom", 1), ("Studio", 0), ("3 Bedrooms, 2 Bathrooms", 3), ("4", 4), (None, None), ("", None)],
)
def test_parse_bedrooms(text, expected):
    assert parse_bedrooms(text) == expected


def test_parse_date_dayfirst_and_default_year():
    assert parse_date("2 March 2027") == date(2027, 3, 2)
    assert parse_date("04/02/2027") == date(2027, 2, 4)
    assert parse_date("March", default_year=2027).year == 2027
    assert parse_date("not a date") is None


def test_iso_date():
    assert iso_date("2027-01-03T00:00:00+0000") == "2027-01-03"
    assert iso_date("2026-11-16T12:19:25.2070000+00:00") == "2026-11-16"
    assert iso_date(None) is None
