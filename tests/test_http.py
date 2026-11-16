import pytest
import requests

from rentscraper.http import BlockedError, PoliteSession, RobotsDisallowedError, ScrapeError

from .fixtures import CLOUDFLARE_CHALLENGE, FakeHTTP

UA = "rentscraper-test/1.0"


def make(routes, **kw):
    sleeps = []
    fake = FakeHTTP(routes)
    s = PoliteSession(UA, min_delay=kw.pop("min_delay", 0), jitter=0, backoff=1, session=fake, sleep=sleeps.append, **kw)
    return s, fake, sleeps


def test_fetch_ok_and_robots_checked_once():
    s, fake, _ = make({
        "https://a.ie/robots.txt": (200, "User-agent: *\nDisallow: /no\n"),
        "https://a.ie/yes": (200, "hello"),
    })
    assert s.get("https://a.ie/yes").text == "hello"
    assert s.get("https://a.ie/yes").text == "hello"
    assert fake.calls.count("https://a.ie/robots.txt") == 1


def test_robots_disallow_raises():
    s, _, _ = make({"https://a.ie/robots.txt": (200, "User-agent: *\nDisallow: /no\n")})
    with pytest.raises(RobotsDisallowedError):
        s.get("https://a.ie/no/thing")


def test_missing_robots_means_allowed():
    s, _, _ = make({"https://a.ie/robots.txt": (404, ""), "https://a.ie/x": (200, "ok")})
    assert s.get("https://a.ie/x").text == "ok"


def test_cloudflare_challenge_is_blocked_not_bypassed():
    s, fake, _ = make({
        "https://cf.ie/robots.txt": (403, CLOUDFLARE_CHALLENGE, {"cf-mitigated": "challenge"}),
    })
    with pytest.raises(BlockedError):
        s.get("https://cf.ie/listings")
    assert fake.calls == ["https://cf.ie/robots.txt"]  # no retry hammering


def test_challenge_on_page_is_blocked():
    s, _, _ = make({
        "https://cf.ie/robots.txt": (200, ""),
        "https://cf.ie/x": (403, CLOUDFLARE_CHALLENGE),
    })
    with pytest.raises(BlockedError):
        s.get("https://cf.ie/x")


def test_retries_on_server_error_then_succeeds():
    responses = iter([(503, "busy"), (200, "fine")])
    s, fake, sleeps = make({"https://a.ie/robots.txt": (404, ""), "https://a.ie/x": lambda: next(responses)})
    assert s.get("https://a.ie/x").text == "fine"
    assert fake.calls.count("https://a.ie/x") == 2
    assert sleeps  # backoff happened


def test_gives_up_after_max_retries():
    s, fake, _ = make({"https://a.ie/robots.txt": (404, ""), "https://a.ie/x": (500, "err")}, max_retries=2)
    with pytest.raises(ScrapeError):
        s.get("https://a.ie/x")
    assert fake.calls.count("https://a.ie/x") == 2


def test_network_error_is_scrape_error():
    s, _, _ = make({"https://down.ie/robots.txt": requests.ConnectionError("boom")})
    with pytest.raises(ScrapeError):
        s.get("https://down.ie/x")


def test_rate_limit_waits_between_requests():
    s, _, sleeps = make({"https://a.ie/robots.txt": (404, ""), "https://a.ie/x": (200, "ok")}, min_delay=2.0)
    s.get("https://a.ie/x")
    s.get("https://a.ie/x")
    assert any(0 < d <= 2.0 for d in sleeps)
