"""Build the daily GitHub Issue update (``python -m rentscraper.digest``).

Writes ``issue_title.txt`` and ``issue_body.md`` into the output directory;
the workflow posts them with the GitHub CLI using the built-in token, so no
extra credentials are needed. Mentioning the repository owner makes GitHub
send a notification (mobile app push and/or GitHub's notification email,
per the user's GitHub notification settings).

Each listing is a checkbox. Ticking it marks the listing as contacted: the
next run reads the ticked boxes (see ``contacted.py``) and leaves it out.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .contacted import marker

# GitHub rejects issue bodies over 65,536 characters.
MAX_BODY = 60000
SECTION_LIMITS = {1: 40, 2: 30, 3: 15}
DEFAULT_OCCUPANTS = 4


def section_titles(n: int) -> dict[int, str]:
    return {
        1: f"🏠 {n}+ bed entire properties",
        2: f"🛋️ {n - 1} bed entire properties (one person on the sofa bed)",
        3: "🚪 Shared – price is per room (last resort)",
    }


def _occupants(report: dict) -> int:
    return int((report.get("search") or {}).get("occupants") or DEFAULT_OCCUPANTS)


def _load(out_dir: Path) -> tuple[dict, list[dict]]:
    try:
        report = json.loads((out_dir / "run_report.json").read_text(encoding="utf-8"))
        shortlist = json.loads((out_dir / "shortlist.json").read_text(encoding="utf-8"))
        return report, shortlist
    except (OSError, json.JSONDecodeError):
        return {}, []


def headline(out_dir: Path) -> tuple[str, str]:
    """Return (issue title, one-line highlights)."""
    date = datetime.now(timezone.utc).strftime("%a %d %b %Y")
    report, shortlist = _load(out_dir)
    if not report:
        return f"Dublin rentals – {date}", "Results attached below."
    n = _occupants(report)
    full = [x for x in shortlist if x.get("tier") == 1]
    sofa = [x for x in shortlist if x.get("tier") == 2]
    shared = [x for x in shortlist if x.get("tier") == 3]
    new = [x for x in shortlist if x.get("is_new")]
    new_full = [x for x in new if x.get("tier") == 1]
    title = f"Dublin rentals – {date}: {len(full)}× {n}-bed, {len(sofa)}× {n - 1}-bed + sofa, {len(new)} new"
    bits = [
        f"**{len(shortlist)}** matching listings ({len(full)} {n}+ bed, {len(sofa)} {n - 1}-bed + sofa, {len(shared)} shared)",
        f"**{len(new)}** new since the last run" + (f", including **{len(new_full)} {n}+ bed**" if new_full else ""),
        f"{report.get('price_changes', 0)} price changes, {report.get('removed', 0)} removed",
    ]
    if report.get("contacted_hidden"):
        bits.append(f"{report['contacted_hidden']} hidden as already contacted")
    priced = [x for x in shortlist if x.get("tier") in (1, 2) and x.get("cost_per_person_eur")]
    if priced:
        cheapest = min(priced, key=lambda x: x["cost_per_person_eur"])
        bits.append(
            f"cheapest entire place: [€{cheapest['rent_monthly_eur']:,.0f}/month (€{cheapest['cost_per_person_eur']:,.0f} each)]"
            f"({cheapest['url']})"
        )
    return title, " · ".join(bits)


def _esc(s: Optional[str]) -> str:
    return (s or "").replace("[", "(").replace("]", ")").replace("\n", " ").replace("<!--", "")


def checkbox_line(x: dict) -> str:
    """One tickable line per listing, ending with the hidden uid marker."""
    rent = x.get("rent_monthly_eur")
    each = x.get("cost_per_person_eur")
    if x.get("tier") == 3:
        price = f"**€{rent:,.0f}/room**" if rent is not None else "**price ?**"
        size = "room"
    else:
        price = f"**€{rent:,.0f}/mo** (€{each:,.0f} each)" if rent is not None and each is not None else "**price ?**"
        size = f"{x['bedrooms']} bed" if x.get("bedrooms") is not None else "? bed"
    dists = x.get("distances_km") or {}
    dist = " / ".join(f"{name.split()[0]} {km:.1f} km" for name, km in dists.items())
    approx = "≈" if x.get("coords_approximate") and dist else ""
    tags = []
    if x.get("is_new"):
        tags.append("🆕")
    if x.get("price_change"):
        tags.append(f"💶 {x['price_change']}")
    if x.get("duplicate_urls"):
        tags.append(f"+{len(x['duplicate_urls'])} other ad(s)")
    if any(str(n).startswith("Above the") for n in x.get("notes") or []):
        tags.append("💸 above target")
    parts = [price, size, _esc(x.get("area")) or None, f"{approx}{dist}" if dist else None,
             f"[{_esc(x.get('title'))[:70]}]({x.get('url')})", f"{x.get('source')}", f"score {x.get('score')}"]
    line = "- [ ] " + " · ".join(p for p in parts if p)
    if tags:
        line += " " + " ".join(tags)
    line += " " + marker(x["uid"])
    flags = x.get("availability_flags") or []
    if flags:
        line += "\n  ⚠️ " + _esc("; ".join(flags))
    return line


def build_body(out_dir: Path, mention: Optional[str], run_url: Optional[str], data_url: Optional[str]) -> str:
    _, highlights = headline(out_dir)
    report, shortlist = _load(out_dir)
    titles = section_titles(_occupants(report))
    links = []
    if data_url:
        links.append(f"[full summary – cheapest, best locations, near misses, removed]({data_url})")
    if run_url:
        links.append(f"[workflow run & downloadable CSV/JSON]({run_url})")
    out = []
    if mention:
        out.append(f"@{mention.lstrip('@')} – today's rental update.\n")
    out.append(highlights + "\n")
    out.append(
        "> **Tick ☑️ a listing once you've contacted it** – it (and its duplicate ads on other sites) "
        "will be left out of the next update. Untick it to bring it back. Ticks in older update issues count too.\n"
    )
    if links:
        out.append(" · ".join(links) + "\n")
    for tier in (1, 2, 3):
        items = sorted([x for x in shortlist if x.get("tier") == tier], key=lambda x: -(x.get("score") or 0))
        out.append(f"\n### {titles[tier]} ({len(items)})\n")
        if not items:
            out.append("_None this run._\n")
            continue
        shown = items[: SECTION_LIMITS[tier]]
        out.append("\n".join(checkbox_line(x) for x in shown) + "\n")
        if len(items) > len(shown):
            out.append(f"\n_…and {len(items) - len(shown)} more in the full summary._\n")
    body = "\n".join(out)
    if len(body) > MAX_BODY:
        cut = body.rfind("\n- [ ]", 0, MAX_BODY - 200)
        body = body[:cut] + "\n\n_…truncated – see the full summary link above._\n"
    return body


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rentscraper.digest", description="Build the daily GitHub Issue update")
    p.add_argument("--output-dir", default="output")
    p.add_argument("--mention", help="GitHub login to @mention so they get a notification")
    p.add_argument("--run-url")
    p.add_argument("--data-url")
    args = p.parse_args(argv)
    out_dir = Path(args.output_dir)
    if not (out_dir / "summary.md").is_file():
        print(f"no summary.md in {out_dir}", file=sys.stderr)
        return 1
    title, _ = headline(out_dir)
    (out_dir / "issue_title.txt").write_text(title, encoding="utf-8")
    (out_dir / "issue_body.md").write_text(build_body(out_dir, args.mention, args.run_url, args.data_url), encoding="utf-8")
    print(title)
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
