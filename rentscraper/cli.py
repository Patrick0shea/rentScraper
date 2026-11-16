"""Command line interface: ``python -m rentscraper``."""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .config import load_config
from .pipeline import run
from .sources import SOURCES
from .sources.base import OK, PARTIAL


def setup_logging(level: str, log_file: Path | None) -> None:
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stderr)]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, mode="w", encoding="utf-8"))
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=handlers,
        force=True,
    )
    logging.getLogger("urllib3").setLevel(logging.WARNING)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rentscraper", description="Dublin rental scraper for a group of three")
    p.add_argument("--config", help="path to config.json")
    p.add_argument("--sources", help=f"comma separated subset of: {', '.join(SOURCES)}")
    p.add_argument("--output-dir", help="where to write results")
    p.add_argument("--history-file", help="history JSON path")
    p.add_argument("--max-pages", type=int, help="cap search pages per search (quick runs)")
    p.add_argument("--no-details", action="store_true", help="skip detail-page fetches")
    p.add_argument("--min-delay", type=float, help="seconds between requests to one host")
    p.add_argument("--log-level", default=os.environ.get("RENTSCRAPER_LOG_LEVEL", "INFO"))
    args = p.parse_args(argv)

    cfg = load_config(args.config)
    if args.output_dir:
        cfg["output"]["directory"] = args.output_dir
    if args.history_file:
        cfg["output"]["history_file"] = args.history_file
    if args.min_delay is not None:
        cfg["http"]["min_delay_seconds"] = args.min_delay
    for scfg in cfg["sources"].values():
        if args.max_pages:
            for key in ("max_pages", "max_pages_per_search"):
                if key in scfg:
                    scfg[key] = min(scfg[key], args.max_pages)
        if args.no_details and "fetch_details" in scfg:
            scfg["fetch_details"] = False
    only = None
    if args.sources:
        only = [s.strip().lower() for s in args.sources.split(",") if s.strip()]
        unknown = [s for s in only if s not in SOURCES]
        if unknown:
            p.error(f"unknown source(s): {', '.join(unknown)}")

    setup_logging(args.log_level, Path(cfg["output"]["directory"]) / "scraper.log")
    log = logging.getLogger("rentscraper")
    try:
        report = run(cfg, only=only)
    except Exception:
        log.exception("fatal error")
        return 2

    print()
    print(f"Listings collected: {report['total_listings']}  |  shortlisted: {report['shortlisted']}  |  "
          f"new: {report['new']}  |  price changes: {report['price_changes']}  |  removed: {report['removed']}")
    for s in report["sources"]:
        print(f"  {s['source']:<16} {s['status']:<18} {s['listings']:>4} listings  {s['message'][:90]}")
    print(f"Results in {cfg['output']['directory']}/ (summary.md, shortlist.csv/json, all_listings.csv/json)")
    ok = any(s["status"] in (OK, PARTIAL) and s["listings"] for s in report["sources"])
    if not ok:
        log.error("no source returned any listings")
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
