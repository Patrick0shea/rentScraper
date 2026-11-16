from rentscraper.history import History
from rentscraper.models import Listing


def L(sid, price, source="myhome"):
    return Listing(source=source, source_id=sid, url=f"https://x.test/{sid}", title=f"t{sid}", rent_monthly_eur=price)


def test_new_price_change_and_removal(tmp_path):
    path = tmp_path / "h.json"
    h = History(path)
    c = h.update([L("1", 2500), L("2", 2800)], "2026-11-16T00:00:00", {"myhome"})
    assert len(c["new"]) == 2
    h.save()

    h = History(path)
    a = L("1", 2400)
    c = h.update([a], "2026-11-16T08:00:00", {"myhome"})
    assert a.price_change == "€2,500 → €2,400 (−€100)"
    assert not a.is_new and a.date_found == "2026-11-16T00:00:00"
    assert c["removed"] == []  # first miss only
    assert h.listings["myhome:2"]["missed_runs"] == 1

    c = h.update([L("1", 2400)], "2026-11-16T16:00:00", {"myhome"})
    assert [r["uid"] for r in c["removed"]] == ["myhome:2"]
    assert h.listings["myhome:2"]["status"] == "removed"
    assert len(h.listings["myhome:1"]["price_history"]) == 2


def test_failed_source_never_marks_removed(tmp_path):
    h = History(tmp_path / "h.json")
    h.update([L("1", 2500)], "t1", {"myhome"})
    for t in ("t2", "t3", "t4"):
        c = h.update([], t, complete_sources=set())  # myhome failed
        assert c["removed"] == []
    assert h.listings["myhome:1"]["status"] == "active"


def test_relisted(tmp_path):
    h = History(tmp_path / "h.json")
    h.update([L("1", 2500)], "t1", {"myhome"})
    h.update([], "t2", {"myhome"}, removed_after=1)
    assert h.listings["myhome:1"]["status"] == "removed"
    c = h.update([L("1", 2500)], "t3", {"myhome"})
    assert len(c["relisted"]) == 1 and h.listings["myhome:1"]["status"] == "active"


def test_corrupt_history_is_backed_up(tmp_path):
    p = tmp_path / "h.json"
    p.write_text("{not json")
    h = History(p)
    assert h.listings == {}
    assert (tmp_path / "h.corrupt.json").exists()


def test_prune_old_removed(tmp_path):
    h = History(tmp_path / "h.json")
    h.update([L("1", 2500)], "2026-01-01T00:00:00+00:00", {"myhome"})
    h.update([], "2026-01-02T00:00:00+00:00", {"myhome"}, removed_after=1)
    assert h.prune("2026-03-01T00:00:00+00:00", keep_removed_days=120) == 0
    assert h.prune("2026-06-01T00:00:00+00:00", keep_removed_days=120) == 1
    assert h.listings == {}
