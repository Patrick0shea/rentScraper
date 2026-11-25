import json

import pytest

from rentscraper import contacted, digest


def item(uid, tier, rent, each, score, **kw):
    d = {"uid": uid, "tier": tier, "rent_monthly_eur": rent, "cost_per_person_eur": each, "score": score,
         "url": f"https://example.test/{uid}", "title": f"Listing {uid} [Test]", "bedrooms": {1: 4, 2: 3, 3: 5}[tier],
         "area": "Ballsbridge (Dublin 4)", "source": uid.split(":")[0], "is_new": False,
         "distances_km": {"AWS Ballsbridge": 0.6, "Dogpatch Labs": 2.2}, "availability_flags": []}
    d.update(kw)
    return d


@pytest.fixture
def out(tmp_path):
    (tmp_path / "summary.md").write_text("# summary\n", encoding="utf-8")
    shortlist = [
        item("myhome:1", 1, 4200, 1050, 70, is_new=True, notes=["Above the €4,000 target by about €200/month (within the stretch budget)"], availability_flags=["Minimum lease appears to be 12 months"]),
        item("myhome:2", 2, 3200, 800, 65, price_change="€3,300 → €3,200 (−€100)"),
        item("spotahome:3", 3, 800, 800, 30, is_new=True, duplicate_urls=["https://x"]),
    ]
    (tmp_path / "shortlist.json").write_text(json.dumps(shortlist))
    (tmp_path / "run_report.json").write_text(json.dumps({"price_changes": 2, "removed": 1, "contacted_hidden": 4, "search": {"occupants": 4}}))
    return tmp_path


def test_title_and_highlights(out):
    title, hl = digest.headline(out)
    assert "1× 4-bed, 1× 3-bed + sofa, 2 new" in title
    assert "**3** matching listings (1 4+ bed, 1 3-bed + sofa, 1 shared)" in hl and "including **1 4+ bed**" in hl
    assert "2 price changes, 1 removed" in hl and "4 hidden as already contacted" in hl
    assert "€3,200/month (€800 each)](https://example.test/myhome:2)" in hl


def test_body_has_checkbox_per_listing_with_marker(out):
    body = digest.build_body(out, "someone", "https://github.com/o/r/actions/runs/1", "https://github.com/o/r/blob/scraper-data/summary.md")
    assert body.startswith("@someone")
    assert "Tick ☑️ a listing once you've contacted it" in body
    assert body.count("- [ ] ") == 3
    for uid in ("myhome:1", "myhome:2", "spotahome:3"):
        assert body.count(f"<!-- rs:{uid} -->") == 1
    assert "**€4,200/mo** (€1,050 each) · 4 bed" in body and "💸 above target" in body
    assert "4+ bed entire properties" in body and "3 bed entire properties (one person on the sofa bed)" in body
    assert "**€800/room** · room" in body
    assert "⚠️ Minimum lease" in body and "🆕" in body and "💶" in body and "+1 other ad(s)" in body
    assert "[Listing myhome:1 (Test)](https://example.test/myhome:1)" in body  # brackets can't break the link
    assert "actions/runs/1" in body and "blob/scraper-data/summary.md" in body


def test_ticking_a_box_in_the_body_round_trips(out):
    body = digest.build_body(out, None, None, None)
    line = next(l for l in body.splitlines() if "rs:myhome:2" in l)
    ticked = body.replace(line, line.replace("- [ ]", "- [x]", 1))
    assert contacted.ticked_in(body) == set()
    assert contacted.ticked_in(ticked) == {"myhome:2"}


def test_body_truncated_under_github_limit(out):
    many = [item(f"spotahome:{i}", 2, 3000, 750, 50, title="x" * 300) for i in range(400)]
    (out / "shortlist.json").write_text(json.dumps(many))
    digest.SECTION_LIMITS[2], old = 400, digest.SECTION_LIMITS[2]
    try:
        body = digest.build_body(out, None, None, None)
    finally:
        digest.SECTION_LIMITS[2] = old
    assert len(body) < 65536 and "truncated" in body


def test_section_cap_mentions_remainder(out):
    many = [item(f"spotahome:{i}", 3, 800, 800, 30) for i in range(20)]
    (out / "shortlist.json").write_text(json.dumps(many))
    body = digest.build_body(out, None, None, None)
    assert body.count("- [ ] ") == digest.SECTION_LIMITS[3]
    assert "and 5 more in the full summary" in body


def test_cli_writes_files(out):
    assert digest.main(["--output-dir", str(out), "--mention", "someone"]) == 0
    assert (out / "issue_title.txt").read_text().startswith("Dublin rentals")
    assert (out / "issue_body.md").read_text().startswith("@someone")


def test_cli_missing_summary(tmp_path):
    assert digest.main(["--output-dir", str(tmp_path)]) == 1
