"""Source registry."""
from __future__ import annotations

from .base import Source, SourceResult
from .daft import DaftSource, LetIeSource
from .generic import PropertyIeSource, RentIeSource, RoomsForRentSource
from .housinganywhere import HousingAnywhereSource
from .myhome import MyHomeSource
from .spotahome import SpotahomeSource

SOURCES: dict[str, type[Source]] = {
    cls.name: cls
    for cls in (
        MyHomeSource,
        SpotahomeSource,
        HousingAnywhereSource,
        DaftSource,
        PropertyIeSource,
        RentIeSource,
        LetIeSource,
        RoomsForRentSource,
    )
}

__all__ = ["SOURCES", "Source", "SourceResult"]
