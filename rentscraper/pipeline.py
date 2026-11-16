"""End-to-end run: scrape -> enrich -> history -> dedupe -> outputs."""
from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

from . import analysis
from .dedupe import find_duplicates
from .history import History
from .http import PoliteSession
from .models import Listing
from .outputs import build_summary, sort_key, write_csv, write_json
from .sources import SOURCES
from .sources.base import DISABLED, SourceResult

log = logging.getLogger(__name__)


def scrape_all(cfg: dict, session: Optional[PoliteSession] = None, only: Optional[list[str]] = None) -> list[SourceResult]:
    session = session or PoliteSession.from_config(cfg["http"])
    results = []
    for name, src_cfg in cfg.get("sources", {}).items():
        if only and name not in only:
            continue
        cls = SOURCES.get(name)
        if cls is None:
            log.warning("unknown source in config: %s", name)
            continue
        if not src_cfg.get("enabled", True):
            r = SourceResult(name, status=DISABLED, message="disabled in config")
            results.append(r)
            continue
        log.info("=== %s ===", cls.display_name or name)
        results.append(cls(session, src_cfg, cfg["search"]).run())
    log.info("HTTP requests made: %d", session.request_count)
    return results


def analyse(listings: list[Listing], cfg: dict, today: Optional[date] = None) -> list[Listing]:
    for lst in listings:
        analysis.enrich(lst, cfg, today=today)
    return listings


def run(
    cfg: dict,
    session: Optional[PoliteSession] = None,
    only: Optional[list[str]] = None,
    source_results: Optional[list[SourceResult]] = None,
    today: Optional[date] = None,
) -> dict:
    run_ts = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    out_dir = Path(cfg["output"]["directory"])
    out_dir.mkdir(parents=True, exist_ok=True)

    results = source_results if source_results is not None else scrape_all(cfg, session, only)
    listings: list[Listing] = [l for r in results for l in r.listings]
    log.info("collected %d listings from %d sources", len(listings), sum(1 for r in results if r.listings))

    analyse(listings, cfg, today=today)

    history = History(cfg["output"]["history_file"])
    complete = {r.source for r in results if r.complete}
    changes = history.update(
        listings, run_ts, complete, removed_after=int(cfg.get("history", {}).get("removed_after_missed_runs", 2))
    )

    n_groups = find_duplicates(listings, cfg.get("dedupe", {}))
    log.info("duplicate groups: %d", n_groups)

    listings.sort(key=sort_key)
    shortlist = [l for l in listings if analysis.is_shortlisted(l, cfg)]
    landmark_names = [lm["name"] for lm in cfg.get("landmarks", [])]
    source_dicts = [r.to_dict() for r in results]

    write_csv(out_dir / "all_listings.csv", listings, landmark_names)
    write_csv(out_dir / "shortlist.csv", shortlist, landmark_names)
    write_json(out_dir / "all_listings.json", [l.to_dict() for l in listings])
    write_json(out_dir / "shortlist.json", [l.to_dict() for l in shortlist])
    summary = build_summary(shortlist, listings, source_dicts, changes, cfg, run_ts)
    (out_dir / "summary.md").write_text(summary, encoding="utf-8")

    report = {
        "run_at": run_ts,
        "sources": source_dicts,
        "total_listings": len(listings),
        "shortlisted": len(shortlist),
        "duplicate_groups": n_groups,
        "new": len(changes["new"]),
        "price_changes": len(changes["price_changes"]),
        "removed": len(changes["removed"]),
        "relisted": len(changes["relisted"]),
    }
    write_json(out_dir / "run_report.json", report)
    history.record_run({k: v for k, v in report.items() if k != "sources"} | {
        "sources": {r["source"]: {"status": r["status"], "listings": r["listings"]} for r in source_dicts}
    })
    pruned = history.prune(run_ts, int(cfg.get("history", {}).get("keep_removed_days", 120)))
    if pruned:
        log.info("pruned %d long-removed listings from history", pruned)
    history.save()
    log.info(
        "done: %d listings, %d shortlisted, %d new, %d price changes, %d removed",
        len(listings), len(shortlist), len(changes["new"]), len(changes["price_changes"]), len(changes["removed"]),
    )
    return report
