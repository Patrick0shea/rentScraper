"""A polite HTTP client.

* Honest, identifying User-Agent.
* robots.txt is fetched and obeyed for every host (Google-style wildcard
  matching with longest-match precedence, which the stdlib parser lacks).
* Per-host minimum delay between requests (plus jitter, plus Crawl-delay).
* Retries with exponential backoff on 429/5xx/network errors only.
* Detects bot-protection challenges (Cloudflare etc.) and raises
  ``BlockedError`` instead of trying to get around them.
"""
from __future__ import annotations

import logging
import random
import re
import time
from dataclasses import dataclass, field
from typing import Callable, Optional
from urllib.parse import urlsplit

import requests

log = logging.getLogger(__name__)


class ScrapeError(Exception):
    """Base error for a failed fetch."""


class BlockedError(ScrapeError):
    """The site actively refused automated access (bot challenge / 403)."""


class RobotsDisallowedError(ScrapeError):
    """robots.txt disallows the URL for our user agent."""


# --------------------------------------------------------------------------
# robots.txt
# --------------------------------------------------------------------------


@dataclass
class _Group:
    agents: list[str] = field(default_factory=list)
    rules: list[tuple[bool, str]] = field(default_factory=list)  # (allow, pattern)
    crawl_delay: Optional[float] = None


class RobotsRules:
    """Parsed robots.txt supporting ``*`` and ``$`` (RFC 9309 semantics)."""

    def __init__(self, text: str | None, allow_all: bool = False, disallow_all: bool = False):
        self.allow_all = allow_all
        self.disallow_all = disallow_all
        self.groups: list[_Group] = []
        if text:
            self._parse(text)

    def _parse(self, text: str) -> None:
        current: Optional[_Group] = None
        last_was_agent = False
        for raw in text.splitlines():
            line = raw.split("#", 1)[0].strip()
            if not line or ":" not in line:
                continue
            key, _, value = line.partition(":")
            key = key.strip().lower()
            value = value.strip()
            if key == "user-agent":
                if current is None or not last_was_agent:
                    current = _Group()
                    self.groups.append(current)
                current.agents.append(value.lower())
                last_was_agent = True
                continue
            last_was_agent = False
            if current is None:
                continue
            if key in ("allow", "disallow"):
                if key == "disallow" and value == "":
                    continue  # empty disallow == allow everything
                current.rules.append((key == "allow", value))
            elif key == "crawl-delay":
                try:
                    current.crawl_delay = float(value)
                except ValueError:
                    pass

    def _group_for(self, user_agent: str) -> Optional[_Group]:
        ua = user_agent.lower()
        token = ua.split("/", 1)[0].strip()
        best: Optional[_Group] = None
        best_len = -1
        for g in self.groups:
            for a in g.agents:
                if a != "*" and a and (a in token or token in a) and len(a) > best_len:
                    best, best_len = g, len(a)
        if best is not None:
            return best
        for g in self.groups:
            if "*" in g.agents:
                return g
        return None

    @staticmethod
    def _pattern_to_regex(pattern: str) -> re.Pattern:
        anchored = pattern.endswith("$")
        if anchored:
            pattern = pattern[:-1]
        regex = "".join(".*" if ch == "*" else re.escape(ch) for ch in pattern)
        return re.compile("^" + regex + ("$" if anchored else ""))

    def can_fetch(self, user_agent: str, url: str) -> bool:
        if self.allow_all:
            return True
        if self.disallow_all:
            return False
        group = self._group_for(user_agent)
        if group is None:
            return True
        parts = urlsplit(url)
        path = parts.path or "/"
        if parts.query:
            path += "?" + parts.query
        best_len = -1
        allowed = True
        for allow, pattern in group.rules:
            if not pattern:
                continue
            if self._pattern_to_regex(pattern).match(path):
                plen = len(pattern)
                # longest match wins; on a tie, allow wins
                if plen > best_len or (plen == best_len and allow):
                    best_len = plen
                    allowed = allow
        return allowed

    def crawl_delay(self, user_agent: str) -> Optional[float]:
        g = self._group_for(user_agent)
        return g.crawl_delay if g else None


# --------------------------------------------------------------------------
# Bot-challenge detection
# --------------------------------------------------------------------------

_CHALLENGE_MARKERS = (
    "cf-browser-verification",
    "challenge-platform",
    "cf_chl_opt",
    "just a moment...",
    "attention required! | cloudflare",
    "enable javascript and cookies to continue",
    "px-captcha",
    "captcha-delivery.com",
    "_incapsula_resource",
    "verify you are human",
)


def is_bot_challenge(resp: requests.Response) -> bool:
    if resp.headers.get("cf-mitigated", "").lower() == "challenge":
        return True
    if resp.status_code in (403, 429, 503):
        head = resp.text[:20000].lower() if resp.text else ""
        return any(m in head for m in _CHALLENGE_MARKERS)
    return False


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


class PoliteSession:
    def __init__(
        self,
        user_agent: str,
        timeout: float = 30.0,
        min_delay: float = 3.0,
        jitter: float = 1.0,
        max_retries: int = 3,
        backoff: float = 5.0,
        session: Optional[requests.Session] = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.min_delay = min_delay
        self.jitter = jitter
        self.max_retries = max_retries
        self.backoff = backoff
        self.session = session or requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-IE,en;q=0.9",
            }
        )
        self._sleep = sleep
        self._last_request: dict[str, float] = {}
        self._robots: dict[str, RobotsRules] = {}
        self.request_count = 0

    @classmethod
    def from_config(cls, http_cfg: dict) -> "PoliteSession":
        return cls(
            user_agent=http_cfg["user_agent"],
            timeout=http_cfg.get("timeout_seconds", 30),
            min_delay=http_cfg.get("min_delay_seconds", 3.0),
            jitter=http_cfg.get("jitter_seconds", 1.0),
            max_retries=http_cfg.get("max_retries", 3),
            backoff=http_cfg.get("backoff_seconds", 5.0),
        )

    # -- robots --------------------------------------------------------
    def robots_for(self, url: str) -> RobotsRules:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        if origin in self._robots:
            return self._robots[origin]
        robots_url = origin + "/robots.txt"
        self._wait(parts.netloc)
        rules: RobotsRules
        try:
            resp = self.session.get(robots_url, timeout=self.timeout, allow_redirects=True)
            self.request_count += 1
            self._last_request[parts.netloc] = time.monotonic()
            if is_bot_challenge(resp):
                raise BlockedError(f"{robots_url} returned a bot-protection challenge (HTTP {resp.status_code})")
            if resp.status_code == 200:
                rules = RobotsRules(resp.text)
            elif 400 <= resp.status_code < 500:
                # RFC 9309: unavailable robots.txt => no restrictions
                rules = RobotsRules(None, allow_all=True)
            else:
                # server error: be conservative
                rules = RobotsRules(None, disallow_all=True)
        except BlockedError:
            raise
        except requests.RequestException as exc:
            raise ScrapeError(f"could not fetch {robots_url}: {exc}") from exc
        self._robots[origin] = rules
        return rules

    def allowed(self, url: str) -> bool:
        return self.robots_for(url).can_fetch(self.user_agent, url)

    # -- throttling ----------------------------------------------------
    def _wait(self, host: str) -> None:
        last = self._last_request.get(host)
        delay = self.min_delay + (random.uniform(0, self.jitter) if self.jitter else 0)
        rules = self._robots.get(f"https://{host}")
        if rules is not None:
            cd = rules.crawl_delay(self.user_agent)
            if cd:
                delay = max(delay, cd)
        if last is not None:
            remaining = delay - (time.monotonic() - last)
            if remaining > 0:
                self._sleep(remaining)

    # -- fetch ---------------------------------------------------------
    def get(self, url: str, check_robots: bool = True) -> requests.Response:
        if check_robots and not self.allowed(url):
            raise RobotsDisallowedError(f"robots.txt disallows {url}")
        host = urlsplit(url).netloc
        last_exc: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            self._wait(host)
            try:
                resp = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                last_exc = exc
                self._last_request[host] = time.monotonic()
                log.warning("GET %s failed (attempt %d/%d): %s", url, attempt, self.max_retries, exc)
                if attempt < self.max_retries:
                    self._sleep(self.backoff * 2 ** (attempt - 1))
                continue
            finally:
                self.request_count += 1
            self._last_request[host] = time.monotonic()
            if is_bot_challenge(resp):
                raise BlockedError(f"{url} returned a bot-protection challenge (HTTP {resp.status_code}); not bypassing")
            if resp.status_code == 403:
                raise BlockedError(f"{url} returned HTTP 403 Forbidden")
            if resp.status_code == 429 or resp.status_code >= 500:
                last_exc = ScrapeError(f"HTTP {resp.status_code} for {url}")
                log.warning("GET %s -> HTTP %d (attempt %d/%d)", url, resp.status_code, attempt, self.max_retries)
                if attempt < self.max_retries:
                    retry_after = resp.headers.get("Retry-After", "")
                    wait = float(retry_after) if retry_after.isdigit() else self.backoff * 2 ** (attempt - 1)
                    self._sleep(min(wait, 120))
                continue
            if resp.status_code >= 400:
                raise ScrapeError(f"HTTP {resp.status_code} for {url}")
            log.debug("GET %s -> %d (%d bytes)", url, resp.status_code, len(resp.content))
            return resp
        raise ScrapeError(f"giving up on {url}: {last_exc}")
