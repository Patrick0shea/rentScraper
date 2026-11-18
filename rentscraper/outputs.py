"""CSV / JSON / Markdown outputs."""
from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any, Iterable, Optional

from .analysis import avg_distance
from .models import TIER_SHARED, TIER_THREE_BED, TIER_TWO_BED, Listing

CSV_COLUMNS = [
    "score", "tier_label", "title", "address", "area", "rent_monthly_eur", "rent_text",
    "total_monthly_for_group_eur", "cost_per_person_eur", "within_budget", "bedrooms", "bathrooms",
    "property_type", "accommodation", "dist_aws_km", "dist_dogpatch_km", "avg_distance_km",
    "coords_approximate", "available_from", "availability_flags", "notes", "price_change", "is_new",
    "status", "contacted", "source", "url", "duplicate_group", "duplicate_urls", "date_found", "date_scraped",
    "listed_on", "latitude", "longitude", "description", "uid",
]


def _row(lst: Listing, landmark_names: list[str]) -> dict[str, Any]:
    d = lst.to_dict()
    names = landmark_names + [None, None]
    d["dist_aws_km"] = lst.distances_km.get(names[0]) if names[0] else None
    d["dist_dogpatch_km"] = lst.distances_km.get(names[1]) if names[1] else None
    d["avg_distance_km"] = avg_distance(lst)
    d["availability_flags"] = "; ".join(lst.availability_flags)
    d["notes"] = "; ".join(lst.notes)
    d["duplicate_urls"] = " ".join(lst.duplicate_urls)
    return {k: d.get(k) for k in CSV_COLUMNS}


def write_csv(path: Path, listings: Iterable[Listing], landmark_names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=CSV_COLUMNS)
        w.writeheader()
        for lst in listings:
            w.writerow(_row(lst, landmark_names))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False, default=str)


def sort_key(lst: Listing) -> tuple:
    return (-(lst.score or 0), lst.cost_per_person_eur or 1e9)


# --------------------------------------------------------------------------
# Markdown summary
# --------------------------------------------------------------------------

def _eur(v: Optional[float]) -> str:
    return "—" if v is None else f"€{v:,.0f}"


def _km(v: Optional[float]) -> str:
    return "—" if v is None else f"{v:.1f} km"


def _md_escape(s: Optional[str]) -> str:
    return (s or "").replace("|", "/").replace("\n", " ")


def _table(listings: list[Listing], landmark_names: list[str]) -> str:
    if not listings:
        return "_None found this run._\n"
    l1 = landmark_names[0] if landmark_names else None
    l2 = landmark_names[1] if len(landmark_names) > 1 else None
    head = (
        f"| Score | Property | Area | Beds | Rent / month | Per person | {l1 or 'Dist 1'} | {l2 or 'Dist 2'} | Flags | Source |\n"
        "|---:|---|---|---:|---:|---:|---:|---:|---|---|\n"
    )
    rows = []
    for x in listings:
        approx = " ≈" if x.coords_approximate else ""
        flags = "; ".join(x.availability_flags) or "—"
        extras = []
        if x.is_new:
            extras.append("🆕")
        if x.price_change:
            extras.append(f"price {x.price_change}")
        if x.duplicate_urls:
            extras.append(f"+{len(x.duplicate_urls)} duplicate ad(s)")
        title = _md_escape(x.title)[:80]
        rent = _eur(x.rent_monthly_eur) + (" /room" if x.tier == TIER_SHARED else "")
        if x.tier == TIER_SHARED:
            beds = "room"
        else:
            beds = str(x.bedrooms) if x.bedrooms is not None else "—"
        rows.append(
            f"| {x.score if x.score is not None else '—'} | [{title}]({x.url}){' ' + ' '.join(extras) if extras else ''} "
            f"| {_md_escape(x.area) or '—'} | {beds} | {rent} "
            f"| {_eur(x.cost_per_person_eur)} | {_km(x.distances_km.get(l1)) if l1 else '—'}{approx} "
            f"| {_km(x.distances_km.get(l2)) if l2 else '—'}{approx} | {_md_escape(flags)} | {x.source} |"
        )
    return head + "\n".join(rows) + "\n"


def build_summary(
    shortlist: list[Listing],
    all_listings: list[Listing],
    source_results: list[dict],
    changes: dict[str, list],
    cfg: dict,
    run_ts: str,
) -> str:
    s = cfg["search"]
    top = int(cfg.get("output", {}).get("summary_top_n", 10))
    names = [lm["name"] for lm in cfg.get("landmarks", [])]
    three = sorted([x for x in shortlist if x.tier == TIER_THREE_BED], key=sort_key)
    two = sorted([x for x in shortlist if x.tier == TIER_TWO_BED], key=sort_key)
    shared = sorted([x for x in shortlist if x.tier == TIER_SHARED], key=sort_key)
    cheapest = sorted(shortlist, key=lambda x: (x.cost_per_person_eur or 1e9, -(x.score or 0)))
    located = sorted(
        [x for x in shortlist if avg_distance(x) is not None],
        key=lambda x: (avg_distance(x), -(x.score or 0)),
    )
    near_miss = sorted(
        [
            x for x in all_listings
            if x.tier in (TIER_THREE_BED, TIER_TWO_BED) and x.status == "active"
            and not x.extra.get("_duplicate_secondary") and not x.contacted
            and x.total_monthly_for_group_eur
            and s["max_total_monthly_rent_eur"] < x.total_monthly_for_group_eur <= s["max_total_monthly_rent_eur"] * 1.1
            and (avg_distance(x) or 0) <= (s.get("max_distance_km") or 99)
        ],
        key=sort_key,
    )

    out = []
    out.append("# Dublin rental search – results\n\n")
    out.append(
        f"Run: **{run_ts}** · Group of {s['occupants']} · Budget ≤ {_eur(s['max_total_monthly_rent_eur'])}/month total, "
        f"≤ {_eur(s['max_per_person_monthly_eur'])} per person · Period {s['rental_start']} → {s['rental_end']}\n\n"
    )
    out.append(
        f"Distances are straight-line from {' and '.join(names)}. Scores are 0–100 (price, bedrooms, proximity, area). "
        "≈ means the position is estimated from the area name. Every listing comes from the linked advert; "
        "nothing is invented. Always confirm details with the advertiser.\n\n"
    )
    out.append("## Sources this run\n\n")
    out.append("| Source | Status | Listings | Pages | Notes |\n|---|---|---:|---:|---|\n")
    for r in source_results:
        out.append(f"| {r['source']} | {r['status']} | {r['listings']} | {r['pages_fetched']} | {_md_escape(r['message'])[:160]} |\n")
    out.append(
        f"\nTotal listings collected: **{len(all_listings)}** · Matching requirements (after de-duplication): **{len(shortlist)}** "
        f"(3-bed: {len(three)}, 2-bed: {len(two)}, shared: {len(shared)})\n"
    )
    out.append(f"\n## Best 3-bedroom properties\n\n{_table(three[:top], names)}")
    out.append(f"\n## Best 2-bedroom alternatives (sofa bed needed)\n\n{_table(two[:top], names)}")
    out.append(f"\n## Shared accommodation (last resort – price is per room)\n\n{_table(shared[:top], names)}")
    out.append(f"\n## Cheapest per person\n\n{_table(cheapest[:top], names)}")
    out.append(f"\n## Best locations (closest to both offices)\n\n{_table(located[:top], names)}")
    if near_miss:
        out.append(f"\n## Near misses (up to 10% over budget – may be negotiable)\n\n{_table(near_miss[:top], names)}")
    new_short = [x for x in shortlist if x.is_new]
    out.append(f"\n## New matching listings this run ({len(new_short)})\n\n{_table(sorted(new_short, key=sort_key)[:top * 2], names)}")
    if changes.get("price_changes"):
        pcs = [x for x in changes["price_changes"] if not x.extra.get("_duplicate_secondary")]
        out.append("\n## Price changes\n\n")
        for x in pcs[: top * 2]:
            out.append(f"- [{_md_escape(x.title)}]({x.url}) – {x.price_change} ({x.source})\n")
    if changes.get("removed"):
        out.append("\n## Removed since last run\n\n")
        contacted_uids = set(changes.get("contacted_uids", []))
        for r in changes["removed"][: top * 3]:
            mark = "☑️ contacted · " if r.get("uid") in contacted_uids else ""
            out.append(
                f"- {mark}[{_md_escape(r.get('title'))}]({r.get('url')}) – {_eur(r.get('rent_monthly_eur'))}, "
                f"{r.get('bedrooms', '—')} bed, first seen {str(r.get('first_seen'))[:10]}, last seen {str(r.get('last_seen'))[:10]} ({r.get('source')})\n"
            )
    contacted_now = sorted(
        [x for x in all_listings if x.contacted and not x.extra.get("_duplicate_secondary")], key=sort_key
    )
    if contacted_now:
        out.append(f"\n## Already contacted – hidden from the lists above ({len(contacted_now)})\n\n")
        for x in contacted_now:
            change = f", price {x.price_change}" if x.price_change else ""
            out.append(f"- [{_md_escape(x.title)}]({x.url}) – {_eur(x.rent_monthly_eur)}{change}, still advertised ({x.source})\n")
    out.append(
        "\n## Notes\n\n"
        "- Shared listings: price shown is per room; total assumes three rooms at that price.\n"
        "- 2-bed options assume one person uses a sofa bed or similar – check the living space.\n"
        "- Flags highlight adverts whose stated dates or lease terms may not cover January–May 2027. "
        "Most standard Irish lettings ask for 12 months, so always confirm a 5-month term.\n"
        "- Full data: `shortlist.csv/json` (matches) and `all_listings.csv/json` (everything collected).\n"
    )
    return "".join(out)
