"""Base class shared by every source scraper."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

from ..http import BlockedError, PoliteSession, RobotsDisallowedError, ScrapeError
from ..models import Listing

# Source run statuses
OK = "ok"  # every configured search page was fetched
PARTIAL = "partial"  # some pages failed or a page cap was hit
BLOCKED = "blocked"  # bot protection / 403 — not bypassed
ROBOTS = "robots_disallowed"
UNREACHABLE = "unreachable"
ERROR = "error"
DISABLED = "disabled"


@dataclass
class SourceResult:
    source: str
    status: str = OK
    listings: list[Listing] = field(default_factory=list)
    pages_fetched: int = 0
    detail_pages_fetched: int = 0
    errors: list[str] = field(default_factory=list)
    message: str = ""
    duration_s: float = 0.0

    @property
    def complete(self) -> bool:
        """True when results can be trusted to detect removed listings."""
        return self.status == OK

    def to_dict(self) -> dict:
        return {
            "source": self.source,
            "status": self.status,
            "listings": len(self.listings),
            "pages_fetched": self.pages_fetched,
            "detail_pages_fetched": self.detail_pages_fetched,
            "errors": self.errors[:20],
            "message": self.message,
            "duration_s": round(self.duration_s, 1),
        }


class Source:
    """Subclasses implement :meth:`scrape`, appending to ``self.result``."""

    name: str = "base"
    base_url: str = ""
    display_name: str = ""

    def __init__(self, session: PoliteSession, cfg: dict, search_cfg: dict):
        self.session = session
        self.cfg = cfg or {}
        self.search_cfg = search_cfg
        self.log = logging.getLogger(f"rentscraper.{self.name}")
        self.result = SourceResult(self.name)
        self.now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    # -- helpers ---------------------------------------------------------
    def url(self, path: str) -> str:
        return path if path.startswith("http") else self.base_url.rstrip("/") + path

    def fetch(self, url: str) -> str:
        resp = self.session.get(url)
        return resp.text

    def page_failed(self, url: str, exc: Exception) -> None:
        msg = f"{url}: {exc}"
        self.log.warning("page failed: %s", msg)
        self.result.errors.append(msg)
        if self.result.status == OK:
            self.result.status = PARTIAL

    def is_candidate(self, listing: Listing) -> bool:
        """Cheap pre-filter deciding whether a detail page is worth fetching."""
        max_total = self.search_cfg.get("max_total_monthly_rent_eur", 3000)
        max_pp = self.search_cfg.get("max_per_person_monthly_eur", 1000)
        rent = listing.rent_monthly_eur
        if rent is None:
            return False
        if listing.accommodation == "shared":
            return rent <= max_pp
        if listing.bedrooms is not None and listing.bedrooms < 2:
            return False
        return rent <= max_total

    def new_listing(self, **kw) -> Listing:
        kw.setdefault("source", self.name)
        kw.setdefault("date_scraped", self.now)
        return Listing(**kw)

    # -- entry point -----------------------------------------------------
    def scrape(self) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def run(self) -> SourceResult:
        start = time.monotonic()
        if not self.cfg.get("enabled", True):
            self.result.status = DISABLED
            self.result.message = "disabled in config"
            return self.result
        try:
            self.scrape()
        except BlockedError as exc:
            self.result.status = BLOCKED
            self.result.message = str(exc)
            self.log.warning("%s blocked automated access: %s", self.name, exc)
        except RobotsDisallowedError as exc:
            self.result.status = ROBOTS
            self.result.message = str(exc)
            self.log.warning("%s: %s", self.name, exc)
        except ScrapeError as exc:
            self.result.status = UNREACHABLE if not self.result.listings else PARTIAL
            self.result.message = str(exc)
            self.log.warning("%s failed: %s", self.name, exc)
        except Exception as exc:  # never let one site crash the whole run
            self.result.status = ERROR if not self.result.listings else PARTIAL
            self.result.message = f"{type(exc).__name__}: {exc}"
            self.log.exception("%s crashed", self.name)
        finally:
            self.result.duration_s = time.monotonic() - start
        if self.result.status in (OK, PARTIAL) and not self.result.message:
            self.result.message = f"{len(self.result.listings)} listings"
        self.log.info(
            "%s finished: status=%s listings=%d pages=%d details=%d",
            self.name,
            self.result.status,
            len(self.result.listings),
            self.result.pages_fetched,
            self.result.detail_pages_fetched,
        )
        return self.result


def first_present(*values: Optional[object]) -> Optional[object]:
    for v in values:
        if v not in (None, "", [], {}):
            return v
    return None
