"""Persistent listing history: first seen, price changes, removals.

Stored as a JSON file so it is easy to inspect and diff. Removal is only
inferred for sources whose run completed successfully, so a website outage
never marks its listings as removed.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Iterable

from .models import Listing

log = logging.getLogger(__name__)

VERSION = 1
SNAPSHOT_FIELDS = (
    "source", "url", "title", "address", "rent_monthly_eur", "bedrooms",
    "property_type", "accommodation", "cost_per_person_eur",
)
MAX_RUNS_KEPT = 500


class History:
    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)
        self.data: dict[str, Any] = {"version": VERSION, "runs": [], "listings": {}}
        if self.path.is_file():
            try:
                self.data = json.loads(self.path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                backup = self.path.with_suffix(".corrupt.json")
                log.error("history file %s is corrupt; moved to %s and starting fresh", self.path, backup)
                self.path.replace(backup)
        self.data.setdefault("runs", [])
        self.data.setdefault("listings", {})

    @property
    def listings(self) -> dict[str, dict]:
        return self.data["listings"]

    def update(
        self,
        current: Iterable[Listing],
        run_ts: str,
        complete_sources: set[str],
        removed_after: int = 2,
    ) -> dict[str, list]:
        """Merge this run's listings. Mutates listings (date_found, is_new, price_change).

        Returns a dict with lists of 'new', 'price_changes', 'removed', 'relisted'.
        """
        changes: dict[str, list] = {"new": [], "price_changes": [], "removed": [], "relisted": []}
        seen: set[str] = set()
        for lst in current:
            seen.add(lst.uid)
            rec = self.listings.get(lst.uid)
            price = lst.rent_monthly_eur
            snapshot = {k: getattr(lst, k) for k in SNAPSHOT_FIELDS}
            if rec is None:
                self.listings[lst.uid] = {
                    "first_seen": run_ts,
                    "last_seen": run_ts,
                    "status": "active",
                    "missed_runs": 0,
                    "removed_at": None,
                    "price_history": [{"date": run_ts, "price": price}],
                    "snapshot": snapshot,
                }
                lst.is_new = True
                lst.date_found = run_ts
                changes["new"].append(lst)
                continue
            lst.date_found = rec.get("first_seen")
            if rec.get("status") == "removed":
                changes["relisted"].append(lst)
                lst.notes.append(f"Relisted (was removed {rec.get('removed_at', '')[:10]})")
            last_price = rec["price_history"][-1]["price"] if rec.get("price_history") else None
            if price is not None and last_price is not None and abs(price - last_price) >= 1:
                diff = price - last_price
                lst.price_change = f"€{last_price:,.0f} → €{price:,.0f} ({'+' if diff > 0 else '−'}€{abs(diff):,.0f})"
                rec["price_history"].append({"date": run_ts, "price": price})
                changes["price_changes"].append(lst)
            elif last_price is None and price is not None:
                rec.setdefault("price_history", []).append({"date": run_ts, "price": price})
            rec.update(last_seen=run_ts, status="active", missed_runs=0, removed_at=None, snapshot=snapshot)

        for uid, rec in self.listings.items():
            if uid in seen or rec.get("status") == "removed":
                continue
            source = uid.split(":", 1)[0]
            if source not in complete_sources:
                continue  # can't tell; the site may simply have failed this run
            rec["missed_runs"] = rec.get("missed_runs", 0) + 1
            if rec["missed_runs"] >= removed_after:
                rec["status"] = "removed"
                rec["removed_at"] = run_ts
                changes["removed"].append({"uid": uid, **rec["snapshot"], "first_seen": rec["first_seen"], "last_seen": rec["last_seen"]})
        return changes

    def prune(self, now_iso: str, keep_removed_days: int = 120) -> int:
        """Forget listings removed more than ``keep_removed_days`` ago."""
        from datetime import datetime, timedelta

        try:
            cutoff = datetime.fromisoformat(now_iso) - timedelta(days=keep_removed_days)
        except ValueError:
            return 0
        drop = []
        for uid, rec in self.listings.items():
            if rec.get("status") != "removed" or not rec.get("removed_at"):
                continue
            try:
                if datetime.fromisoformat(rec["removed_at"]) < cutoff:
                    drop.append(uid)
            except ValueError:
                continue
        for uid in drop:
            del self.listings[uid]
        return len(drop)

    def record_run(self, run_info: dict) -> None:
        self.data["runs"].append(run_info)
        self.data["runs"] = self.data["runs"][-MAX_RUNS_KEPT:]

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".history-", suffix=".json")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(self.data, fh, indent=1, ensure_ascii=False, sort_keys=True)
        os.replace(tmp, self.path)
