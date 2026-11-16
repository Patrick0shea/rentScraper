from rentscraper.http import RobotsRules

UA = "rentscraper/1.0 (+https://example.org)"

MYHOME_LIKE = """
User-agent: *
Disallow: /feed
Allow: /rentals/*?page=
Disallow: /rentals/*?page=*&
Disallow: /rentals/*?

User-agent: GPTBot
Disallow: /
"""


def test_myhome_style_longest_match():
    r = RobotsRules(MYHOME_LIKE)
    assert r.can_fetch(UA, "https://www.myhome.ie/rentals/dublin/property-to-rent-in-dublin-4")
    assert r.can_fetch(UA, "https://www.myhome.ie/rentals/dublin/property-to-rent-in-dublin-4?page=2")
    assert not r.can_fetch(UA, "https://www.myhome.ie/rentals/dublin/property-to-rent-in-dublin-4?page=2&maxprice=3000")
    assert not r.can_fetch(UA, "https://www.myhome.ie/rentals/dublin/property-to-rent?maxprice=3000")
    assert not r.can_fetch(UA, "https://www.myhome.ie/feed")


def test_specific_agent_group_wins():
    r = RobotsRules(MYHOME_LIKE)
    assert not r.can_fetch("GPTBot", "https://www.myhome.ie/rentals/x")


def test_spotahome_style_rules():
    r = RobotsRules("User-agent: *\nDisallow: /*?budget*\nDisallow: /*?move-*\nDisallow: /api/*\n")
    assert r.can_fetch(UA, "https://www.spotahome.com/s/dublin--ireland/page:2")
    assert not r.can_fetch(UA, "https://www.spotahome.com/s/dublin--ireland?budget=0-1000")
    assert not r.can_fetch(UA, "https://www.spotahome.com/api/x")


def test_housinganywhere_style_rules():
    r = RobotsRules("User-agent: *\nDisallow: /api/*\nDisallow: /*/s/*?*\n")
    assert r.can_fetch(UA, "https://housinganywhere.com/s/Dublin--Ireland?page=2")
    assert not r.can_fetch(UA, "https://housinganywhere.com/de/s/Dublin--Irland?page=2")
    assert not r.can_fetch(UA, "https://housinganywhere.com/api/v1/search")


def test_dollar_anchor_and_empty_disallow():
    r = RobotsRules("User-agent: *\nDisallow: /international$\nDisallow:\n")
    assert not r.can_fetch(UA, "https://x.ie/international")
    assert r.can_fetch(UA, "https://x.ie/internationalisation")


def test_allow_all_and_disallow_all():
    assert RobotsRules(None, allow_all=True).can_fetch(UA, "https://x.ie/a")
    assert not RobotsRules(None, disallow_all=True).can_fetch(UA, "https://x.ie/a")


def test_crawl_delay():
    r = RobotsRules("User-agent: *\nCrawl-delay: 7\nDisallow: /x\n")
    assert r.crawl_delay(UA) == 7.0
