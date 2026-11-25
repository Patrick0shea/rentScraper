# rentScraper – Dublin rentals for four (January–May 2027)

A polite, tested rental scraper that searches several Irish rental websites for
accommodation for **four people in Dublin from January to May 2027**. It
ranks what it finds against a fixed budget and two workplaces: AWS in
Ballsbridge and Dogpatch Labs.

It runs locally or automatically on GitHub Actions three times a day, keeps a
history of every advert it has seen, and reports new listings, price changes
and removed adverts.

> **Every property in the results comes from a real advert and links back to
> it.** The scraper never invents properties, prices, availability or
> addresses. Fields a site doesn't publish are left blank. Always confirm
> details with the advertiser.

---

## What it does

| Requirement | How it is handled |
|---|---|
| Budget around €4,000/month total (€1,000/person), stretching to €4,400 | Entire property: rent ÷ 4. Shared: rent is per room, so the total assumes 4 rooms at that price. Listings between €4,000 and €4,400 (€1,100/person) are still shortlisted but score lower on price and are marked 💸 *above target*. Anything over the stretch limit is excluded from the shortlist (kept in `all_listings`). Set `budget_stretch_pct` to 0 in `config.json` for a hard €4,000 cap. |
| 1st choice: entire 4+ bed | Tier 1, highest bedroom score |
| 2nd choice: entire 3-bed + couch / sofa bed | Tier 2, flagged "one person needs the sofa bed". 2-beds and smaller are excluded. |
| Last resort: shared | Tier 3, price per room |
| Location | Distance to both offices (straight line), plus a bonus for the named areas (Ballsbridge, Donnybrook, Sandymount, Ringsend, Irishtown, Grand Canal Dock, Docklands, IFSC, North Wall, East Wall, Pearse Street) and for Dublin 1/2/4 |
| Group size | `search.occupants` in `config.json` (now 4). The tiers follow it: N+ beds, then N−1 beds + sofa, then shared rooms. |
| Score (0–100) | 35% price per person, 30% bedrooms, 25% proximity, 10% area, minus a penalty for availability risk. Weights are in `config.json`. |
| Jan–May 2027 availability | Flags: available only after early January; available only until a date before end of May ("till Spring 2027"); minimum lease longer than 5 months ("12 month lease", "1 year lease", "long-term let"); availability not stated. Listings that only become free in May or later are excluded. |
| Entire vs shared | From each site's property type, plus keyword detection ("room to rent", "house share", …) on general sites |
| Duplicates across sites | Same bedrooms, price within 4%, and either coordinates within 120 m or near-identical addresses. Exact reposts on the same site are merged too. Duplicate links are kept. |
| History | `data/history.json`: first seen, last seen, price history, status (active/removed). A listing is "removed" only after it has been missing from **two** runs in which its site was scraped completely. A website outage never marks listings as removed. |

## Websites

Status as observed from a cloud server on 16 November 2026.

| Site | Status | How |
|---|---|---|
| **MyHome.ie** | ✅ Working | Server-rendered search JSON (`ng-state`) for Dublin 1, 2, 3, 4. Detail pages are fetched for in-budget 3+ bed candidates (description, Eircode). robots.txt allows the clean paths and `?page=N`. It disallows other query strings, so filtering happens locally. |
| **Spotahome** | ✅ Working | Mid-term platform (1–11+ months), well suited to a 5-month let. Listing data comes from the server-rendered page payload, with clean `/page:N` pagination. `?budget=` and `?move-in=` are disallowed by robots.txt, so they are not used. |
| **HousingAnywhere** | ✅ Working | Mid-term platform. Server-rendered listing cards (about 8 per page). Detail pages give coordinates. `/api/*` is disallowed by robots.txt and is **not** used. |
| **Daft.ie** | ⛔ Blocked | Cloudflare managed challenge (`cf-mitigated: challenge`) for automated clients, including on `robots.txt`. The scraper reports `blocked` and moves on; it does not bypass the challenge. A parser for Daft's page data is included in case access becomes possible. Daft's partner API needs a key issued by Daft and isn't used. |
| **Property.ie** | ⛔ Blocked | Same Cloudflare challenge (Daft group). Parser included for the same reason. |
| **Rent.ie** | ⛔ Blocked | Same Cloudflare challenge (Daft group). |
| **Let.ie** | ↪ Redirects to Daft.ie | Let.ie now forwards to Daft.ie, so it is covered by (and blocked with) Daft. |
| **RoomsForRent.ie** | ❌ Unreachable | The server did not answer (gateway 502). Retried each run and reported as `unreachable`. |

Every run's status for each site is shown at the top of `summary.md` and in
`run_report.json`. A failure on one site never stops the others.

**Using the blocked sites yourself:** Daft.ie, Property.ie and Rent.ie all
offer free saved-search email alerts. Set up an alert for Dublin 1/2/4,
3+ beds, max €4,400 to cover those sites without automation.

### Why no Playwright?

Every working source serves its listings in the initial HTML, so `requests` and
BeautifulSoup are enough. A headless browser would only matter for the
Cloudflare-protected sites, and using one to get past their challenge is the
kind of access-control bypass this project deliberately avoids. Playwright is
therefore not a dependency.

## Politeness

* Honest User-Agent identifying the project
* robots.txt is fetched and obeyed for every host, with full wildcard (`*`, `$`) longest-match rules
* At least 3 s (+ jitter) between requests to the same site; `Crawl-delay` is respected
* Retries only on 429/5xx/network errors, with exponential backoff and `Retry-After`
* Bot challenges, CAPTCHAs and 403s are detected and **never bypassed**
* About 60–120 requests per run in total, spread across sites

## Installation

Requires Python 3.10+.

```bash
git clone https://github.com/Patrick0shea/rentScraper.git
```

```bash
cd rentScraper
```

```bash
python -m venv .venv && source .venv/bin/activate
```

```bash
pip install -r requirements-dev.txt
```

(`requirements.txt` alone is enough to run the scraper; `requirements-dev.txt` adds pytest.)

## Usage

```bash
python -m rentscraper
```

A full run takes about 5–10 minutes because of the delays. Results go to `output/`:

| File | Contents |
|---|---|
| `summary.md` | Readable report: site status, best 4+ beds, best 3-beds (+ sofa), shared options, cheapest per person, best locations, near misses (up to 10% over the €4,400 maximum), new listings, price changes, removed listings. All entries link to the original adverts. |
| `shortlist.csv` / `.json` | Listings that meet the requirements (de-duplicated), best first |
| `all_listings.csv` / `.json` | Everything collected this run, including over-budget and duplicates |
| `run_report.json` | Per-site status, counts and errors |
| `scraper.log` | Full log |

History is kept in `data/history.json`.

Useful options:

```bash
python -m rentscraper --sources myhome,spotahome --max-pages 1 --no-details
```

```bash
python -m rentscraper --help
```

Configuration lives in `config.json`: group size, budget and stretch, dates, landmark coordinates,
priority areas, scoring weights, per-site search paths and page caps, and HTTP
politeness. Some settings can also be overridden with environment variables;
see `.env.example`. **No API keys or credentials are needed.**

> The AWS Ballsbridge coordinate in `config.json` is an approximate point in
> Ballsbridge. If you know the exact office entrance, update `landmarks` and
> the distances will follow.

## Tests

```bash
python -m pytest
```

* **Unit tests:** price/bedroom/date parsing, robots.txt matching, the HTTP
  client (retries, rate limiting, challenge detection), area detection and
  distances, classification, cost per person, budget filter, availability
  flags, scoring, de-duplication, and history (new, price change, removal,
  relisting, pruning).
* **Offline integration tests:** the full pipeline against synthetic versions
  of each site, including blocked and unreachable sites, cross-site
  duplicates, and a three-run history check. Test fixtures are clearly
  synthetic ("Test Road") and never reach real results.
* **Live tests** (opt-in) hit the real websites with one page each:

```bash
python -m pytest --live -k live
```

## Automation (GitHub Actions)

`.github/workflows/scrape.yml`:

* **Schedule:** 07:17, 13:17 and 19:17 UTC daily (Dublin is UTC+0 in winter, UTC+1 in summer).
* **Manual:** *Actions → Rental scraper → Run workflow*, optionally limiting sources or pages.
* **Tests** run first, and on every push or PR that touches code.
* **Artifacts:** every run uploads `output/` and `history.json` as `rental-results-<run>`, kept for 30 days.
* **Historical data:** history and the latest results are committed to a separate
  **`scraper-data`** branch, so `main` stays clean. The next run restores the history
  from there. Browse `scraper-data/summary.md` on GitHub to see the latest report.
* **Failure handling:** a site that fails is reported in the summary. The job
  fails only if *no* site returned listings, and artifacts are uploaded either way.
* **No secrets:** only the built-in `GITHUB_TOKEN` is used, to push to `scraper-data`.
  If your repository restricts workflow permissions, enable *Settings → Actions →
  General → Workflow permissions → Read and write*.

### Daily update issue

After the 07:17 UTC run each day, the workflow opens a GitHub Issue labelled
`rental-update`. It has a headline (match counts, new listings, the cheapest
entire place), then every matching listing as a **checkbox**: price, cost
each, bedrooms, area, distances, a link to the advert, and any availability
warning. It @mentions the repository owner, so GitHub sends you a
notification: a push in the **GitHub mobile app**, and/or an email, depending
on your GitHub notification settings. The previous day's update issue is
closed automatically. To post one on demand, run the workflow manually with
**post_update** ticked. This uses only the built-in `GITHUB_TOKEN`; no setup is
needed.

### Marking listings as contacted

**Tick the checkbox** next to a listing in any update issue (on the web or in
the GitHub app) once you've contacted it. Before every scrape, the workflow
reads the ticked boxes from all update issues, open or closed. Those listings
are left out of the next update and the shortlist, along with their duplicate
adverts on other sites. To bring one back, **untick** it.

For anything you contacted that isn't in an update issue, add its advert URL
(or its `uid` from `shortlist.csv`) to [`contacted.txt`](contacted.txt) and commit.

Contacted listings are still tracked. The summary lists them under *Already
contacted*, and if one is taken down it is marked ☑️ in *Removed since last
run*, which is a useful hint that it has been let.

Note: GitHub pauses scheduled workflows in repositories with no activity for 60
days. The scraper's own commits to `scraper-data` count as activity.

## Project layout

```
rentscraper/
  cli.py            command line entry point (python -m rentscraper)
  config.py         config.json + environment overrides
  http.py           polite session: robots.txt, rate limits, retries, block detection
  models.py         Listing data model
  parsing.py        price / bedroom / date parsing
  geo.py            distances, Dublin districts, area matching
  analysis.py       classification, cost per person, budget, availability flags, scoring
  dedupe.py         duplicate detection
  contacted.py      listings ticked as contacted (issue checkboxes, contacted.txt)
  digest.py         daily update issue with checkboxes
  history.py        persistent history, price changes, removals
  outputs.py        CSV / JSON / Markdown summary
  pipeline.py       orchestration
  sources/          one module per website
tests/              unit, offline integration and opt-in live tests
config.json         all settings
contacted.txt       listings you contacted outside the update issues
```

## Limitations

* Daft.ie, Property.ie, Rent.ie and Let.ie, the largest Irish rental sites, block
  automated access, so their listings aren't included (see the email-alert tip above).
* Distances are straight-line, not walking or public-transport times.
* Most standard Irish lettings are 12-month leases. The scraper flags stated terms,
  but many adverts don't mention lease length, so a 5-month term must always be confirmed.
* Spotahome shows a "from" price that can vary with the dates you book.
* HousingAnywhere only server-renders about 8 listings per search page, so
  its coverage is a subset of what the site shows in a browser.
* Site layouts change. When a page can't be parsed, the source is reported as
  `partial`/`error` in the summary instead of silently returning nothing, and
  the tests show which parser needs updating.
