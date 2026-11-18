"""Listings you've already contacted, so they are left out of future updates.

Two ways to mark a listing:

1. Tick its checkbox in a daily ``rental-update`` GitHub Issue. Every
   checkbox line ends with a hidden ``<!-- rs:<uid> -->`` marker. Before each
   scrape, the workflow downloads all update issues and runs::

       python -m rentscraper.contacted --issues issues.json --out data/contacted.json

   Unticking the box brings the listing back on the next run.

2. Add the advert URL (or its uid, e.g. ``myhome:5037809``) on its own line
   in ``contacted.txt`` at the repository root.

A contacted listing hides its duplicate adverts on other sites too.
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from pathlib import Path
from typing import Iterable

from .models import Listing

log = logging.getLogger(__name__)

MARKER = "rs:"
CHECKBOX_RE = re.compile(r"^[ \t]*[-*+][ \t]+\[([ xX])\][^\n]*?<!--\s*rs:(\S+?)\s*-->", re.M)


def marker(uid: str) -> str:
    return f"<!-- {MARKER}{uid} -->"


def ticked_in(body: str | None) -> set[str]:
    """uids whose checkbox is ticked in one issue body."""
    if not body:
        return set()
    return {m.group(2) for m in CHECKBOX_RE.finditer(body) if m.group(1) in "xX"}


def ticked_in_issues(issues: Iterable[dict]) -> set[str]:
    out: set[str] = set()
    for issue in issues:
        if isinstance(issue, dict):
            out |= ticked_in(issue.get("body"))
    return out


def load_manual(path: Path) -> tuple[set[str], set[str]]:
    """(uids, urls) from a contacted.txt-style file. '#' starts a comment."""
    uids: set[str] = set()
    urls: set[str] = set()
    if not path.is_file():
        return uids, urls
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry = line.split()[0]
        if entry.startswith("http"):
            urls.add(normalise_url(entry))
        elif ":" in entry:
            uids.add(entry)
    return uids, urls


def normalise_url(url: str) -> str:
    return url.split("#", 1)[0].split("?", 1)[0].rstrip("/").lower()


def load(contacted_file: str | None, manual_file: str | None) -> tuple[set[str], set[str]]:
    uids: set[str] = set()
    urls: set[str] = set()
    if contacted_file and Path(contacted_file).is_file():
        try:
            data = json.loads(Path(contacted_file).read_text(encoding="utf-8"))
            uids |= set(data.get("uids", []))
        except (json.JSONDecodeError, AttributeError) as exc:
            log.warning("ignoring unreadable %s: %s", contacted_file, exc)
    if manual_file:
        m_uids, m_urls = load_manual(Path(manual_file))
        uids |= m_uids
        urls |= m_urls
    return uids, urls


def apply(listings: list[Listing], uids: set[str], urls: set[str]) -> int:
    """Mark contacted listings (and every duplicate in their group). Returns count marked."""
    if not uids and not urls:
        return 0
    groups: set[str] = set()
    for lst in listings:
        if lst.uid in uids or normalise_url(lst.url) in urls:
            lst.contacted = True
            if lst.duplicate_group:
                groups.add(lst.duplicate_group)
    for lst in listings:
        if lst.duplicate_group in groups:
            lst.contacted = True
    return sum(1 for l in listings if l.contacted)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rentscraper.contacted",
                                description="Collect listings ticked as contacted in the daily update issues")
    p.add_argument("--issues", required=True, help="JSON from: gh issue list --json number,body")
    p.add_argument("--out", required=True, help="where to write {\"uids\": [...]}")
    args = p.parse_args(argv)
    try:
        issues = json.loads(Path(args.issues).read_text(encoding="utf-8") or "[]")
    except (OSError, json.JSONDecodeError) as exc:
        print(f"could not read {args.issues}: {exc}; treating as no issues", file=sys.stderr)
        issues = []
    uids = sorted(ticked_in_issues(issues if isinstance(issues, list) else []))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps({"uids": uids}, indent=1), encoding="utf-8")
    print(f"{len(uids)} listing(s) ticked as contacted across {len(issues)} update issue(s)")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
