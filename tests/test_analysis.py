from datetime import date

from rentscraper.analysis import availability_flags, enrich, is_shortlisted
from rentscraper.models import ENTIRE, SHARED, TIER_OTHER, TIER_SHARED, TIER_FULL, TIER_SOFA, Listing

TODAY = date(2026, 11, 16)
START, END = date(2027, 1, 1), date(2027, 5, 31)

BALLSBRIDGE = (53.3300, -6.2320)
FAR_AWAY = (53.2800, -6.4500)  # ~15 km out


def make(**kw):
    base = dict(source="myhome", source_id=kw.pop("sid", "1"), url="https://example.test/1", title="Test listing",
                accommodation=ENTIRE, address="Test Road, Ballsbridge, Dublin 4")
    base.update(kw)
    return Listing(**base)


def test_entire_property_cost_per_person(cfg):
    l = enrich(make(rent_monthly_eur=3600, bedrooms=4, latitude=BALLSBRIDGE[0], longitude=BALLSBRIDGE[1]), cfg, TODAY)
    assert l.cost_per_person_eur == 900
    assert l.total_monthly_for_group_eur == 3600
    assert l.tier == TIER_FULL
    assert l.tier_label == "4+ bed entire property"
    assert l.within_budget is True
    assert l.area.startswith("Ballsbridge")
    assert set(l.distances_km) == {"AWS Ballsbridge", "Dogpatch Labs"}


def test_shared_room_cost_is_per_room(cfg):
    l = enrich(make(rent_monthly_eur=900, accommodation=SHARED, bedrooms=4), cfg, TODAY)
    assert l.cost_per_person_eur == 900
    assert l.total_monthly_for_group_eur == 3600
    assert l.tier == TIER_SHARED
    assert any("4 rooms needed" in n for n in l.notes)


def test_budget_stretches_ten_percent_over_4000(cfg):
    at_target = enrich(make(sid="a", rent_monthly_eur=4000, bedrooms=4), cfg, TODAY)
    stretch = enrich(make(sid="b", rent_monthly_eur=4400, bedrooms=4), cfg, TODAY)
    over = enrich(make(sid="c", rent_monthly_eur=4401, bedrooms=4), cfg, TODAY)
    assert at_target.within_budget and not any("Above the" in n for n in at_target.notes)
    assert stretch.within_budget and is_shortlisted(stretch, cfg)
    assert any("Above the €4,000 target by about €400" in n for n in stretch.notes)
    assert stretch.score < at_target.score
    assert over.within_budget is False and not is_shortlisted(over, cfg)


def test_budget_without_stretch_is_hard_limit(cfg):
    cfg["search"]["budget_stretch_pct"] = 0
    l = enrich(make(rent_monthly_eur=4001, bedrooms=4), cfg, TODAY)
    assert l.within_budget is False


def test_shared_room_per_person_limit(cfg):
    ok = enrich(make(sid="a", rent_monthly_eur=1050, accommodation=SHARED), cfg, TODAY)
    too_much = enrich(make(sid="b", rent_monthly_eur=1150, accommodation=SHARED), cfg, TODAY)
    assert ok.within_budget is True
    assert too_much.within_budget is False


def test_three_bed_is_sofa_tier_and_smaller_excluded(cfg):
    three = enrich(make(sid="3", rent_monthly_eur=3400, bedrooms=3), cfg, TODAY)
    two = enrich(make(sid="2", rent_monthly_eur=2400, bedrooms=2), cfg, TODAY)
    one = enrich(make(sid="1", rent_monthly_eur=1800, bedrooms=1), cfg, TODAY)
    assert three.tier == TIER_SOFA and is_shortlisted(three, cfg)
    assert three.cost_per_person_eur == 850
    assert any("sofa bed" in n for n in three.notes)
    assert two.tier == TIER_OTHER and not is_shortlisted(two, cfg)
    assert one.tier == TIER_OTHER and not is_shortlisted(one, cfg)


def test_tiers_follow_group_size(cfg):
    cfg["search"]["occupants"] = 3
    two = enrich(make(rent_monthly_eur=2400, bedrooms=2), cfg, TODAY)
    assert two.tier == TIER_SOFA and two.tier_label == "2 bed entire property (sofa bed needed)"


def test_room_ad_on_general_site_is_classified_shared(cfg):
    l = enrich(make(source="daft", rent_monthly_eur=850, bedrooms=1, title="Double room to rent in house share"), cfg, TODAY)
    assert l.accommodation == SHARED


def test_score_prefers_four_bed_close_and_cheap(cfg):
    a = enrich(make(sid="a", rent_monthly_eur=3500, bedrooms=4, latitude=BALLSBRIDGE[0], longitude=BALLSBRIDGE[1]), cfg, TODAY)
    b = enrich(make(sid="b", rent_monthly_eur=3500, bedrooms=3, latitude=BALLSBRIDGE[0], longitude=BALLSBRIDGE[1]), cfg, TODAY)
    c = enrich(make(sid="c", rent_monthly_eur=3500, bedrooms=4, address="Somewhere", latitude=FAR_AWAY[0], longitude=FAR_AWAY[1]), cfg, TODAY)
    assert a.score > b.score
    assert a.score > c.score
    assert not is_shortlisted(c, cfg)  # beyond max_distance_km


def test_no_price_means_no_score(cfg):
    l = enrich(make(rent_monthly_eur=None, bedrooms=4), cfg, TODAY)
    assert l.score is None and l.within_budget is None and not is_shortlisted(l, cfg)


def test_late_availability_excluded_from_shortlist(cfg):
    l = enrich(make(source="spotahome", rent_monthly_eur=3500, bedrooms=4, available_from="2027-11-22"), cfg, TODAY)
    assert not is_shortlisted(l, cfg)


# --- availability flags ---------------------------------------------------

def flags(**kw):
    return availability_flags(make(**kw), START, END, TODAY)


def test_flag_available_after_start():
    f = flags(available_from="2027-03-02")
    assert any(x.startswith("Available only from 02 Mar 2027") for x in f)


def test_flag_until_spring():
    f = flags(description="** Short Term Rental - Available till Spring 2027 ** Lovely cottage")
    assert any("until spring 2027" in x for x in f)


def test_flag_until_specific_month():
    f = flags(description="Available until March 2027 only.")
    assert any(x.startswith("Available only until") for x in f)


def test_flag_minimum_12_month_lease():
    f = flags(description="Minimum 12 month lease required. References essential.")
    assert any(x.startswith("Minimum lease appears to be 12") for x in f)


def test_flag_one_year_lease():
    f = flags(description="Offered on a 1 year lease.")
    assert any("12 months" in x for x in f)


def test_six_month_minimum_flagged_but_five_not():
    assert any("Minimum lease" in x for x in flags(description="minimum of 6 months"))
    assert not any("Minimum lease" in x for x in flags(description="minimum 5 months", available_from="2027-01-01"))


def test_flag_long_term():
    f = flags(description="Long term let only, professionals preferred")
    assert any("long-term" in x for x in f)


def test_flag_available_now_on_standard_site():
    f = flags(description="Available now. Fully furnished.")
    assert any(x.startswith("Available now") for x in f)


def test_early_availability_not_flagged_on_mid_term_platform():
    f = flags(source="spotahome", available_from="2026-11-16")
    assert f == []


def test_unknown_availability_flagged():
    f = flags(description="Bright apartment close to the DART.")
    assert any("not stated" in x for x in f)


def test_short_term_note():
    l = make(description="Short-term let considered")
    availability_flags(l, START, END, TODAY)
    assert any("short/flexible" in n for n in l.notes)
