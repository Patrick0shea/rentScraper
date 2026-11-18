import json

from rentscraper import contacted
from rentscraper.models import Listing

BODY = """intro text
- [x] **€2,995/mo** · 3 bed · [40 Test Lane](https://example.test/a) <!-- rs:myhome:1 -->
  ⚠️ some flag
- [ ] **€2,200/mo** · 2 bed <!-- rs:myhome:2 -->
* [X] room <!-- rs:spotahome:3 -->
- [x] ticked but no marker
- [ ] unticked <!-- rs:housinganywhere:ut4 -->
text mentioning <!-- rs:myhome:9 --> outside a checkbox
"""


def L(source, sid, url=None, group=None):
    l = Listing(source=source, source_id=sid, url=url or f"https://{source}.test/{sid}", title="t")
    l.duplicate_group = group
    return l


def test_ticked_in_only_returns_checked_markers():
    assert contacted.ticked_in(BODY) == {"myhome:1", "spotahome:3"}
    assert contacted.ticked_in(None) == set()


def test_ticked_in_issues_unions_and_ignores_junk():
    issues = [{"number": 1, "body": BODY}, {"number": 2, "body": "- [x] x <!-- rs:daft:7 -->"}, {"number": 3, "body": None}, "junk"]
    assert contacted.ticked_in_issues(issues) == {"myhome:1", "spotahome:3", "daft:7"}


def test_load_manual(tmp_path):
    p = tmp_path / "contacted.txt"
    p.write_text("# comment\n\nhttps://Example.test/A/?ref=x#frag\nspotahome:5\n   # indented comment\nnot-a-uid\n")
    uids, urls = contacted.load_manual(p)
    assert uids == {"spotahome:5"}
    assert urls == {"https://example.test/a"}
    assert contacted.load_manual(tmp_path / "missing.txt") == (set(), set())


def test_apply_marks_duplicates_and_urls():
    a, b, c, d = L("myhome", "1", group="g1"), L("spotahome", "9", group="g1"), L("daft", "5", url="https://example.test/a"), L("myhome", "8")
    n = contacted.apply([a, b, c, d], {"myhome:1"}, {"https://example.test/a"})
    assert (a.contacted, b.contacted, c.contacted, d.contacted) == (True, True, True, False)
    assert n == 3


def test_load_combines_sources(tmp_path):
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"uids": ["myhome:1"]}))
    m = tmp_path / "contacted.txt"
    m.write_text("spotahome:2\nhttps://x.test/3\n")
    uids, urls = contacted.load(str(f), str(m))
    assert uids == {"myhome:1", "spotahome:2"} and urls == {"https://x.test/3"}
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert contacted.load(str(bad), None) == (set(), set())


def test_cli(tmp_path):
    issues = tmp_path / "issues.json"
    issues.write_text(json.dumps([{"number": 1, "body": BODY}]))
    out = tmp_path / "data" / "contacted.json"
    assert contacted.main(["--issues", str(issues), "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == {"uids": ["myhome:1", "spotahome:3"]}
    (tmp_path / "empty.json").write_text("")
    assert contacted.main(["--issues", str(tmp_path / "empty.json"), "--out", str(out)]) == 0
    assert json.loads(out.read_text()) == {"uids": []}
