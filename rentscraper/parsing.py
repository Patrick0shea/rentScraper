"""Text parsing helpers: prices, bedroom counts, dates."""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Optional

from dateutil import parser as dateparser

WEEKS_PER_MONTH = 52 / 12

_PRICE_RE = re.compile(r"€\s*([\d][\d,\.]*)|([\d][\d,\.]*)\s*(?:€|eur\b|euro)", re.I)


def _to_number(s: str) -> Optional[float]:
    s = s.strip()
    if not s:
        return None
    # "2,500" / "2.500" (thousands) / "2500.00"
    if re.fullmatch(r"\d{1,3}([,\.]\d{3})+", s):
        s = re.sub(r"[,\.]", "", s)
    else:
        s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


def parse_monthly_price(text: Optional[str]) -> Optional[float]:
    """Parse a rent string into a monthly euro amount.

    Handles '€2,200 / month', '€550 per week', '2500 €/month', '€1,200 pcm'.
    Returns None when no price is stated (e.g. 'Price on application').
    """
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    amount = _to_number(m.group(1) or m.group(2))
    if amount is None or amount <= 0:
        return None
    # Unit is taken from the words right after the amount, so
    # "€1,200 per month (€277 per week)" stays monthly.
    lower = re.split(r"[(€\n]", text[m.end(): m.end() + 25], maxsplit=1)[0].lower()
    if re.search(r"(per|/|a)\s*week|weekly|p/?w\b|pw\b", lower):
        amount = amount * WEEKS_PER_MONTH
    elif re.search(r"(per|/|a)\s*(night|day)|nightly", lower):
        return None  # short-stay pricing is not comparable; don't guess
    return round(amount, 2)


def parse_int(text: Optional[str | int | float]) -> Optional[int]:
    if text is None:
        return None
    if isinstance(text, (int, float)):
        return int(text)
    m = re.search(r"\d+", str(text))
    return int(m.group(0)) if m else None


def parse_bedrooms(text: Optional[str]) -> Optional[int]:
    """'3 beds' -> 3, 'Studio' -> 0, '2 Bed' -> 2, None -> None."""
    if text is None:
        return None
    t = str(text).lower()
    if "studio" in t:
        return 0
    m = re.search(r"(\d+)\s*(?:-\s*)?(?:bed|bedroom|br\b)", t)
    if m:
        return int(m.group(1))
    m = re.fullmatch(r"\s*(\d+)\s*", t)
    return int(m.group(1)) if m else None


def parse_date(text: Optional[str], default_year: Optional[int] = None) -> Optional[date]:
    if not text:
        return None
    try:
        default = datetime(default_year or date.today().year, 1, 1)
        return dateparser.parse(text, dayfirst=True, fuzzy=True, default=default).date()
    except (ValueError, OverflowError, TypeError):
        return None


def iso_date(value: Optional[str]) -> Optional[str]:
    """Normalise an ISO-ish timestamp to YYYY-MM-DD."""
    if not value:
        return None
    try:
        return dateparser.isoparse(value).date().isoformat()
    except (ValueError, TypeError):
        d = parse_date(value)
        return d.isoformat() if d else None


def clean_text(text: Optional[str]) -> Optional[str]:
    if text is None:
        return None
    t = re.sub(r"\s+", " ", str(text)).strip()
    return t or None
