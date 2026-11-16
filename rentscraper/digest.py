"""Build the daily GitHub Issue update (``python -m rentscraper.digest``).

Writes ``issue_title.txt`` and ``issue_body.md`` into the output directory;
the workflow posts them with the GitHub CLI using the built-in token, so no
extra credentials are needed. Mentioning the repository owner makes GitHub
send a notification (mobile app push and/or GitHub's notification email,
per the user's GitHub notification settings).
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# GitHub rejects issue bodies over 65,536 characters.
MAX_BODY = 60000


def headline(out_dir: Path) -> tuple[str, str]:
    """Return (issue title, one-line highlights)."""
    date = datetime.now(timezone.utc).strftime("%a %d %b %Y")
    try:
        report = json.loads((out_dir / "run_report.json").read_text(encoding="utf-8"))
        shortlist = json.loads((out_dir / "shortlist.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return f"Dublin rentals – {date}", "Results attached below."
    three = [x for x in shortlist if x.get("tier") == 1]
    two = [x for x in shortlist if x.get("tier") == 2]
    shared = [x for x in shortlist if x.get("tier") == 3]
    new = [x for x in shortlist if x.get("is_new")]
    new3 = [x for x in new if x.get("tier") == 1]
    title = f"Dublin rentals – {date}: {len(three)}× 3-bed, {len(two)}× 2-bed, {len(new)} new"
    bits = [
        f"**{len(shortlist)}** matching listings ({len(three)} three-bed, {len(two)} two-bed, {len(shared)} shared)",
        f"**{len(new)}** new since the last run" + (f", including **{len(new3)} three-bed**" if new3 else ""),
        f"{report.get('price_changes', 0)} price changes, {report.get('removed', 0)} removed",
    ]
    priced = [x for x in shortlist if x.get("tier") in (1, 2) and x.get("cost_per_person_eur")]
    if priced:
        cheapest = min(priced, key=lambda x: x["cost_per_person_eur"])
        bits.append(
            f"cheapest entire place: [€{cheapest['rent_monthly_eur']:,.0f}/month (€{cheapest['cost_per_person_eur']:,.0f} each)]"
            f"({cheapest['url']})"
        )
    return title, " · ".join(bits)


def build_body(out_dir: Path, mention: Optional[str], run_url: Optional[str], data_url: Optional[str]) -> str:
    _, highlights = headline(out_dir)
    summary = (out_dir / "summary.md").read_text(encoding="utf-8")
    links = []
    if data_url:
        links.append(f"[latest full summary]({data_url})")
    if run_url:
        links.append(f"[workflow run & downloadable CSV/JSON]({run_url})")
    head = ""
    if mention:
        head += f"@{mention.lstrip('@')} – today's rental update.\n\n"
    head += highlights + "\n\n"
    if links:
        head += " · ".join(links) + "\n\n"
    head += "---\n\n"
    body = head + summary
    if len(body) > MAX_BODY:
        cut = body.rfind("\n", 0, MAX_BODY - 200)
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
