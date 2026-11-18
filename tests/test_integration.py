"""Integration tests: the full pipeline against synthetic sites (offline),
plus opt-in live tests against the real websites (``pytest --live``)."""
import csv
import json
from pathlib import Path

import pytest
import requests

from rentscraper import pipeline
from rentscraper.cli import main
from rentscraper.config import load_config
from rentscraper.http import PoliteSession

from . import fixtures as fx

MH = "https://www.myhome.ie"
SAH = "https://www.spotahome.com"
HA = "https://housinganywhere.com"
D4 = "/rentals/dublin/property-to-rent-in-dublin-4"


def routes(price_3bed=2900, include_2bed=True):
    mh_results = [
        fx.myhome_result(1, 3, price_3bed, "1 Test Road, Ballsbridge, Dublin 4", 53.3300, -6.2320),
        fx.myhome_result(3, 1, 1900, "3 Test Court, Dublin 4", 53.33, -6.23),
        fx.myhome_result(4, 4, 5200, "4 Test Park, Donnybrook, Dublin 4", 53.322, -6.237),
    ]
    if include_2bed:
        mh_results.append(fx.myhome_result(2, 2, 2400, "2 Test Quay, Ringsend, Dublin 4", 53.3410, -6.2260))
    sah_cards = [
        # same flat as MyHome #1 -> duplicate
        fx.spotahome_card("501", "apartment", 3, price_3bed, "3-bedroom apartment for rent in Ballsbridge, Dublin", "Test Road", "D04", -6.23205, 53.33005),
        fx.spotahome_card("502", "room_shared", 3, 900, "Room in shared 3-bedroom flat in Sandymount, Dublin", "Test Lane", "D04", -6.218, 53.330),
    ]
    ha_cards = [fx.ha_card("ut9", "Apartment in Test Street, Dublin", 2750, "3 bedrooms", "Available from 2 March 2027")]
    return {
        MH + "/robots.txt": (200, "User-agent: *\nAllow: /rentals/*?page=\nDisallow: /rentals/*?\n"),
        MH + D4: (200, fx.myhome_search_html(mh_results)),
        **{MH + f"/rentals/brochure/test-{i}/{i}": (200, fx.myhome_brochure_html("Minimum 12 month lease.")) for i in (1, 2, 3, 4)},
        SAH + "/robots.txt": (200, "User-agent: *\nDisallow: /*?budget*\n"),
        SAH + "/s/dublin--ireland": (200, fx.spotahome_search_html(sah_cards)),
        HA + "/robots.txt": (200, "User-agent: *\nDisallow: /api/*\n"),
        HA + "/s/Dublin--Ireland": (200, fx.ha_search_html(ha_cards)),
        HA + "/room/ut9/ie/Dublin/test-street": (200, fx.ha_detail_html(53.345, -6.245, "Synthetic")),
        "https://www.daft.ie/robots.txt": (403, fx.CLOUDFLARE_CHALLENGE, {"cf-mitigated": "challenge"}),
        "https://www.property.ie/robots.txt": (403, fx.CLOUDFLARE_CHALLENGE, {"cf-mitigated": "challenge"}),
        "https://www.rent.ie/robots.txt": (403, fx.CLOUDFLARE_CHALLENGE, {"cf-mitigated": "challenge"}),
        "https://www.let.ie/": (403, fx.CLOUDFLARE_CHALLENGE, {"cf-mitigated": "challenge"}),
        "https://www.roomsforrent.ie/robots.txt": requests.ConnectionError("unreachable"),
    }


def offline_session(r):
    return PoliteSession("rentscraper-test/1.0", min_delay=0, jitter=0, backoff=0, max_retries=1,
                         session=fx.FakeHTTP(r), sleep=lambda s: None)


@pytest.fixture
def offline_cfg(cfg):
    cfg["sources"]["myhome"]["search_paths"] = [D4]
    cfg["sources"]["spotahome"]["max_pages"] = 2
    cfg["sources"]["housinganywhere"]["max_pages"] = 2
    return cfg


def test_full_pipeline_offline(offline_cfg):
    cfg = offline_cfg
    report = pipeline.run(cfg, session=offline_session(routes()))
    out = Path(cfg["output"]["directory"])

    statuses = {s["source"]: s["status"] for s in report["sources"]}
    assert statuses["myhome"] == "ok" and statuses["spotahome"] == "ok" and statuses["housinganywhere"] == "ok"
    assert statuses["daft"] == statuses["propertyie"] == statuses["rentie"] == statuses["letie"] == "blocked"
    assert statuses["roomsforrent"] == "unreachable"
    assert report["total_listings"] == 7

    for name in ("all_listings.csv", "all_listings.json", "shortlist.csv", "shortlist.json", "summary.md", "run_report.json"):
        assert (out / name).is_file(), name

    shortlist = json.loads((out / "shortlist.json").read_text())
    uids = {x["uid"] for x in shortlist}
    assert "myhome:4" not in uids  # €5,200 over budget
    assert "myhome:3" not in uids  # 1 bed
    assert "myhome:2" in uids  # 2-bed fallback
    assert "spotahome:502" in uids  # shared, €900/room
    # the cross-site duplicate appears once in the shortlist
    assert len({"myhome:1", "spotahome:501"} & uids) == 1
    best = shortlist[0]
    assert best["tier"] == 1 and best["bedrooms"] == 3
    assert best["duplicate_urls"]
    by_uid = {x["uid"]: x for x in json.loads((out / "all_listings.json").read_text())}
    assert any(f.startswith("Minimum lease appears to be 12") for f in by_uid["myhome:1"]["availability_flags"])
    assert any(f.startswith("Available only from 02 Mar 2027") for f in by_uid["housinganywhere:ut9"]["availability_flags"])

    with open(out / "shortlist.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert rows and {"cost_per_person_eur", "url", "source", "availability_flags", "date_found"} <= set(rows[0])
    for row in rows:
        assert float(row["total_monthly_for_group_eur"]) <= 3000
        assert float(row["cost_per_person_eur"]) <= 1000

    summary = (out / "summary.md").read_text()
    for heading in ("Best 3-bedroom", "Best 2-bedroom", "Cheapest per person", "Best locations", "Sources this run"):
        assert heading in summary
    assert "https://www.myhome.ie/rentals/brochure/test-1/1" in summary or "https://www.spotahome.com/dublin/for-rent:apartments/501" in summary
    assert "blocked" in summary


def test_history_across_runs_offline(offline_cfg):
    cfg = offline_cfg
    pipeline.run(cfg, session=offline_session(routes(price_3bed=2900)))
    r2 = pipeline.run(cfg, session=offline_session(routes(price_3bed=2800, include_2bed=False)))
    assert r2["new"] == 0
    assert r2["price_changes"] == 2  # myhome:1 and spotahome:501
    r3 = pipeline.run(cfg, session=offline_session(routes(price_3bed=2800, include_2bed=False)))
    assert r3["removed"] == 1  # myhome:2 gone for 2 consecutive complete runs
    summary = (Path(cfg["output"]["directory"]) / "summary.md").read_text()
    assert "Removed since last run" in summary
    hist = json.loads(Path(cfg["output"]["history_file"]).read_text())
    assert hist["listings"]["myhome:2"]["status"] == "removed"
    assert len(hist["runs"]) == 3


def test_failed_site_does_not_remove_its_listings(offline_cfg):
    cfg = offline_cfg
    pipeline.run(cfg, session=offline_session(routes()))
    broken = routes()
    broken[MH + D4] = (503, "down")
    for _ in range(3):
        r = pipeline.run(cfg, session=offline_session(broken))
        assert r["removed"] == 0


def test_contacted_listings_hidden_with_their_duplicates(offline_cfg, tmp_path):
    cfg = offline_cfg
    issues = [{"number": 7, "body": "- [x] ticked <!-- rs:spotahome:501 -->\n- [ ] not <!-- rs:myhome:2 -->"}]
    (tmp_path / "issues.json").write_text(json.dumps(issues))
    from rentscraper import contacted

    cfg["output"]["contacted_file"] = str(tmp_path / "contacted.json")
    assert contacted.main(["--issues", str(tmp_path / "issues.json"), "--out", cfg["output"]["contacted_file"]]) == 0
    manual = tmp_path / "contacted.txt"
    manual.write_text("# contacted by phone\nhttps://www.spotahome.com/dublin/for-rent:rooms/502\n")
    cfg["output"]["contacted_manual_file"] = str(manual)

    report = pipeline.run(cfg, session=offline_session(routes()))
    out = Path(cfg["output"]["directory"])
    uids = {x["uid"] for x in json.loads((out / "shortlist.json").read_text())}
    # spotahome:501 ticked -> it and its MyHome duplicate (myhome:1) are hidden; 502 hidden via contacted.txt
    assert not uids & {"spotahome:501", "myhome:1", "spotahome:502"}
    assert "myhome:2" in uids
    assert report["contacted_hidden"] == 3
    summary = (out / "summary.md").read_text()
    assert "Already contacted – hidden from the lists above" in summary
    all_rows = {x["uid"]: x for x in json.loads((out / "all_listings.json").read_text())}
    assert all_rows["myhome:1"]["contacted"] is True


def test_cli_returns_1_when_nothing_scraped(tmp_path, monkeypatch):
    monkeypatch.setenv("RENTSCRAPER_OUTPUT_DIR", str(tmp_path / "o"))
    monkeypatch.setenv("RENTSCRAPER_HISTORY_FILE", str(tmp_path / "h.json"))
    monkeypatch.setattr(pipeline, "scrape_all", lambda cfg, session=None, only=None: [])
    assert main(["--sources", "myhome"]) == 1
    assert (tmp_path / "o" / "summary.md").is_file()


def test_config_env_overrides(monkeypatch, tmp_path):
    monkeypatch.setenv("RENTSCRAPER_SOURCES", "myhome,spotahome")
    monkeypatch.setenv("RENTSCRAPER_MAX_PAGES", "2")
    cfg = load_config()
    enabled = [k for k, v in cfg["sources"].items() if v["enabled"]]
    assert enabled == ["myhome", "spotahome"]
    assert cfg["sources"]["spotahome"]["max_pages"] == 2


# --- live (opt-in) -------------------------------------------------------------

@pytest.mark.live
@pytest.mark.parametrize("source", ["myhome", "spotahome", "housinganywhere"])
def test_live_source_returns_real_listings(source, cfg):
    from rentscraper.sources import SOURCES

    scfg = dict(cfg["sources"][source])
    for key in ("max_pages", "max_pages_per_search"):
        if key in scfg:
            scfg[key] = 1
    scfg["fetch_details"] = False
    if source == "myhome":
        scfg["search_paths"] = scfg["search_paths"][-1:]
    http = dict(cfg["http"], min_delay_seconds=2)
    res = SOURCES[source](PoliteSession.from_config(http), scfg, cfg["search"]).run()
    assert res.status in ("ok", "partial"), res.message
    assert res.listings, "expected at least one real listing"
    for l in res.listings[:10]:
        assert l.url.startswith("https://")
        assert l.title


@pytest.mark.live
@pytest.mark.parametrize("source", ["daft", "propertyie", "rentie"])
def test_live_protected_sites_are_handled(source, cfg):
    from rentscraper.sources import SOURCES

    scfg = dict(cfg["sources"][source], max_pages_per_search=1)
    scfg["search_paths"] = scfg["search_paths"][:1]
    res = SOURCES[source](PoliteSession.from_config(cfg["http"]), scfg, cfg["search"]).run()
    # Either the site lets us in (then we must parse something) or we report it cleanly.
    assert res.status in ("ok", "partial", "blocked", "unreachable", "robots_disallowed")
