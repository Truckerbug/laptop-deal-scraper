# Laptop Deal Scraper

Watches eBay for used workstation and gaming laptops and parses the listing names.
Scores every listing 0–100 based on specified criteria and creates a live local web app.
Allows you to sort, filter, and search for new terms and refresh the list from the web app,
no manual script re-running necessary.

Two python programs run independently:

- **The scraper** (`src/main.py`) — polls a fixed list of watch queries on a
  schedule (hourly via launchd) and writes everything into a local SQLite DB.
- **The web app** (`src/webapp.py`) — a small Flask server that reads that
  same DB and serves one page. Sorting/filtering happens instantly in the
  browser (all data's already loaded); the search box POSTs a live eBay
  query and drops results straight into the table.

They share state through `data/listings.db` — you can run the web app any
time, whether or not the scheduled scraper has run recently.

## 1. Get eBay API credentials

1. Create a free account at <https://developer.ebay.com/>
2. Go to **My Account → Application Keys** (<https://developer.ebay.com/my/keys>)
3. Create a **production** keyset for a new app
4. On the same dashboard, set **Marketplace Account Deletion** to
   **"Exempted"** and save — production keys won't authenticate until this
   step is done. (This tool only does read-only public listing searches, so
   the exemption is the correct choice — no user account data is touched.)
5. Copy the **Client ID** and **Client Secret**

## 2. Install

```bash
cd laptop-deal-scraper
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
set -a && source .env && set +a
# edit .env and paste in your EBAY_CLIENT_ID / EBAY_CLIENT_SECRET
```

## 3. Run the web app

```bash
source venv/bin/activate   # if not already active
./webapp.sh
```

Open **<http://127.0.0.1:8420>** in a browser. It'll be empty at first — use
the "Search eBay" box to run a live query (e.g. "ThinkPad P1"), or hit
"Rescan all watches" to run every query in `SEARCH_QUERIES` at once.

Sorting: click any column header (Signal, Price, Brand, RAM, GPU, CPU,
Storage, Seen) — click again to reverse direction.

Filtering: score slider, price range, min RAM, brand chips, GPU tier chips,
and a free-text filter, all combine and apply instantly against whatever's
loaded. None of this touches the eBay API — it's just narrowing what's
already in the table.

Broadening search: type anything into the search box and hit Enter/"Search
eBay" — it runs that exact query against eBay right now and merges results
in. Good for one-off checks ("MSI Stealth 16") without permanently adding it
to the scheduled watch list.

## Filling in missing specs (description/item-detail enrichment)

The search endpoint eBay gives us only returns titles, and titles often
don't mention every spec. When a listing is missing GPU, RAM, or storage
after title parsing, the tool can fetch that listing's **full detail** —
a separate API call that returns the seller's structured "item specifics"
(Processor, RAM Size, GPU, Storage Type, etc.) plus the full description.
Structured fields especially are much more reliable than guessing off a
truncated title.

Since it's a per-listing API call and eBay's Browse API has a daily quota,
this doesn't run for everything automatically:

- **Automatic**: new listings that are missing a key spec after title
  parsing get enriched automatically during a scan, capped at
  `MAX_ENRICH_PER_RUN` (default 60) per run so it can't blow through quota.
  Each listing is only attempted once (tracked via an `enriched` flag) —
  it won't keep re-fetching the same listing on every hourly run.
- **On demand, one at a time**: any row still missing a spec shows a small
  "Fetch specs" button in the web UI — click it to fetch and re-parse just
  that listing.
- **On demand, in bulk**: the "Fill in missing specs" button in the top
  control bar enriches up to 40 not-yet-enriched listings at once — handy
  for catching up a backlog (e.g. right after upgrading to this version).

Tune this in `src/config.py`:

- `ENRICH_ENABLED` — turn automatic enrichment off entirely if you'd rather conserve API quota and only ever enrich manually
- `MAX_ENRICH_PER_RUN` — per-scan cap on detail-fetch calls
- `DESCRIPTION_CHAR_LIMIT` — how much of the description text to feed into
  parsing (capped since descriptions often end in unrelated seller
  boilerplate/return-policy text)

## Sold/removed listings

The search endpoint only returns currently-active listings, but nothing
automatically deletes a listing once it sells — it would otherwise just sit
in the DB forever. Instead, listings that haven't shown up again in a while
get checked directly against eBay (a sold/ended listing 404s on lookup,
which is authoritative — unlike "it didn't appear in this run's search
results," which can also happen to a still-active listing that fell outside
eBay's top-50-newest results for a popular query).

- **Automatic**: every scheduled scan checks a batch of stale-but-still-
  "active" listings (default: anything not re-seen in 20+ hours), capped at
  `MAX_SOLD_CHECKS_PER_RUN` (default 30) per run.
- **On demand**: the "Check for sold" button in the web app runs the same
  check immediately.
- **In the UI**: sold/ended listings are hidden by default (the "Hide
  sold/ended" checkbox in the filter row) rather than deleted — turn it off
  to see them with a SOLD tag, useful for checking what something like this
  actually went for.

Tune in `src/config.py`: `STALE_CHECK_HOURS` (how long before a listing is
worth re-checking) and `MAX_SOLD_CHECKS_PER_RUN`.

## 4. Tune the scheduled watch list

Edit `src/config.py`:

- `SEARCH_QUERIES` — the queries "Rescan all watches" and the hourly cron
  job run. Add/remove models here for anything you want tracked automatically.
- `MIN_PRICE` / `MAX_PRICE` — price window considered at all
- `SPEC_TARGETS` — target price, RAM floor/target, and `min_score_to_alert`
  (only affects the terminal-log "new deal" alert and the stat in the header
   — the web UI itself shows everything regardless of score, you just filter
   with the slider)
- `GPU_TIERS` — which GPUs are worth how many points
- `WORKSTATION_MODEL_BONUS` / `BRAND_KEYWORDS` — chassis families / brand
  detection used for scoring and the Brand column+filter
- `EXCLUDE_TERMS` — titles containing these are dropped entirely

Run `python3 tests/test_pipeline.py` after changes — it runs the whole
parse → score → store pipeline against a handful of fake listings (no
network needed) so you can sanity-check scoring/parsing changes fast.

## 5. Schedule the scraper (background watch queries)

```bash
cp launchd/com.spencer.laptopscraper.plist ~/Library/LaunchAgents/
# edit the copied plist first — replace YOUR_USERNAME with your actual path
launchctl load ~/Library/LaunchAgents/com.spencer.laptopscraper.plist
```

Runs once immediately, then every hour. Logs to `data/run.log`.

## 6. Keep the web app always running (optional)

If you'd rather not manually start `./webapp.sh` each time, launchd can keep
it running in the background and auto-restart it if it ever crashes:

```bash
cp launchd/com.spencer.laptopscraper.webapp.plist ~/Library/LaunchAgents/
# edit the copied plist first — replace YOUR_USERNAME with your actual path
launchctl load ~/Library/LaunchAgents/com.spencer.laptopscraper.webapp.plist
```

Then <http://127.0.0.1:8420> is just always there — open it whenever, no
terminal needed. To stop either job:

```bash
launchctl unload ~/Library/LaunchAgents/com.spencer.laptopscraper.plist
launchctl unload ~/Library/LaunchAgents/com.spencer.laptopscraper.webapp.plist
```

## How scoring works

Each listing gets scored 0–100 from five weighted signals parsed out of the
title (`src/parser.py`) and combined in `src/scorer.py`:

| Signal | Max points |
| ---------------------------------- | -----------: |
| Price vs. target budget | 30 |
| GPU tier (workstation > gaming) | 25 |
| RAM (target: 32GB+) | 20 |
| Storage | 10 |
| Known workstation chassis | 10 |
| Dual M.2/NVMe mentioned | 5 |

The parser also pulls out CPU, brand, and total storage capacity for
display/filtering — these don't affect the score (but may in the future),
they're just surfaced as columns so you can sort/filter by them directly.

Listings matching an exclude term (parts, broken, etc.) always score 0 and
are excluded from processing entirely (for now).

## Known limitations

- Title parsing is regex-based and best-effort — eBay titles are messy, so
  RAM/GPU/CPU/brand detection will sometimes miss or misfire. Worth
  eyeballing results rather than trusting any single field blindly.
- No image/description parsing — just the title text eBay returns in search
  results.
- The web app is a local dev server (Flask's built-in one) — fine for a
  personal tool on localhost, not meant to be exposed to the internet.
- Free-tier eBay Browse API has generous but not unlimited rate limits;
  hourly polling across ~15 queries plus occasional ad-hoc searches is well
  within normal limits.

  ### Todo
  
  - Add AMD GPUs to tierlist
  - Update search query list
  - Add toggle for parts, broken, etc.
  
