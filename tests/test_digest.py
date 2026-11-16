import json

import pytest

from rentscraper import digest


@pytest.fixture
def out(tmp_path):
    (tmp_path / "summary.md").write_text("# Dublin rental search – results\n\n## Best 3-bedroom properties\n\nrow\n", encoding="utf-8")
    shortlist = [
        {"tier": 1, "is_new": True, "cost_per_person_eur": 950, "rent_monthly_eur": 2850, "url": "https://example.test/a"},
        {"tier": 2, "is_new": False, "cost_per_person_eur": 700, "rent_monthly_eur": 2100, "url": "https://example.test/b"},
        {"tier": 3, "is_new": True, "cost_per_person_eur": 800, "rent_monthly_eur": 800, "url": "https://example.test/c"},
    ]
    (tmp_path / "shortlist.json").write_text(json.dumps(shortlist))
    (tmp_path / "run_report.json").write_text(json.dumps({"price_changes": 2, "removed": 1}))
    return tmp_path


def test_title_and_highlights(out):
    title, hl = digest.headline(out)
    assert "1× 3-bed, 1× 2-bed, 2 new" in title
    assert "**3** matching listings" in hl and "including **1 three-bed**" in hl
    assert "2 price changes, 1 removed" in hl
    assert "€2,100/month (€700 each)](https://example.test/b)" in hl  # cheapest entire place


def test_body_mentions_and_links(out):
    body = digest.build_body(out, "someone", "https://github.com/o/r/actions/runs/1", "https://github.com/o/r/blob/scraper-data/summary.md")
    assert body.startswith("@someone")
    assert "actions/runs/1" in body and "blob/scraper-data/summary.md" in body
    assert "## Best 3-bedroom properties" in body


def test_body_truncated_under_github_limit(out):
    (out / "summary.md").write_text("line of text\n" * 10000, encoding="utf-8")
    body = digest.build_body(out, None, None, None)
    assert len(body) < 65536 and body.rstrip().endswith("_…truncated – see the full summary link above._")


def test_cli_writes_files(out):
    assert digest.main(["--output-dir", str(out), "--mention", "someone"]) == 0
    assert (out / "issue_title.txt").read_text().startswith("Dublin rentals")
    assert (out / "issue_body.md").read_text().startswith("@someone")


def test_cli_missing_summary(tmp_path):
    assert digest.main(["--output-dir", str(tmp_path)]) == 1
