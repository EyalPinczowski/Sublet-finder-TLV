# TLV Sublet Finder

Watches Tel Aviv Facebook groups for people **offering** a sublet, checks
each one against your own price/rooms/neighborhood/roommate/bathroom
criteria, scores and ranks the matches, and pings you on Telegram — with a
summary, the address, a phone/WhatsApp link, the post's photos, and a link
back to the post itself — the instant a good one shows up.

Everything beyond the core scan/match/notify loop is **optional and off by
default**: skip any of it and the tool keeps working with what's configured.

## How it works

1. Log into Facebook once to create a session:
   - **No display available (e.g. Termux/proot)**: `python scripts/login_facebook_headless.py`
     asks for your email and password right in the terminal (password hidden)
     and logs in headlessly. If Facebook challenges the login, it asks you
     for the code, or tells you to approve it from your phone's Facebook app.
     Note: Facebook may throw a CAPTCHA at headless logins — if it does,
     you'll need a real screen (below) since a CAPTCHA has to be clicked by
     a human, not scripted.
   - **Normal machine with a screen**: `python scripts/login_facebook.py`
     opens a real visible browser for you to log in.
   Either way, the session is saved to `data/storage_state.json`.
2. `scripts/scan.py` uses that session to open each group in `config.yaml`,
   pulls recent posts, and for each new one that looks like an *offer* (not
   someone else looking for a place), extracts price/rooms/address/
   roommates/bathrooms/phone/photos and checks it against your `search`
   criteria (and, if configured, the zone-distance check below). Extraction
   uses the Gemini LLM when `GEMINI_API_KEY` is set (far more reliable on
   colloquial Hebrew), automatically falling back to a regex/keyword parser
   otherwise or whenever the LLM is unavailable this run. Everything is
   stored in `data/listings.db` (SQLite), so re-running never double-
   processes a post — including cross-posts and comment-less posts with no
   recoverable permalink, which are matched on their content instead.
3. Every match is scored 0-100 (`src/scoring.py`) and sent to Telegram —
   with a summary, price/rooms/roommates/bathrooms, the address, a phone/
   WhatsApp link when there is one, a link to the post, a Google Maps link,
   and the post's own photos — plus ⭐ Save / 🗑 Dismiss buttons if you're
   running the [vote listener](#telegram-vote-buttons).
4. `scripts/matches.py` lists everything that's matched so far, best score
   first, whether or not Telegram is set up.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

Edit `config.yaml` with the groups you're a member of, your own search
criteria (price range, neighborhoods, room/roommate/bathroom requirements),
and the `llm:`/`zone:` blocks described below.

Copy `.env.example` to `.env` and fill in whichever of the following you
want — **every one of them is optional**, and the tool degrades gracefully
(falls back or simply skips that feature) when a given one is left unset:

| Variable | Enables | Get it from |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Instant match alerts | [@BotFather](https://t.me/BotFather) to create a bot + message it once, then `https://api.telegram.org/bot<TOKEN>/getUpdates` for your chat id |
| `GEMINI_API_KEY` | LLM-based extraction (recommended) | https://aistudio.google.com/apikey (free tier) |
| `GOOGLE_SHEET_ID` | [Google Sheets sink](#google-sheets) | see below |
| `DASHBOARD_TOKEN` | [Live dashboard](#dashboard) | any random string — auto-generated if left blank |
| `SITE_REPO_URL` | [Published snapshot](#publishing-a-snapshot) | a dedicated repo you create |

Skip all of them to just run `scripts/scan.py` and check
`scripts/matches.py` by hand.

### LLM-based extraction

With `GEMINI_API_KEY` set and `llm.enabled: true` in `config.yaml` (the
default), each post is sent to Gemini's free tier for extraction — far more
reliable on colloquial Hebrew than the regex parser, and it also classifies
offer-vs-seeker posts and writes a real one-line summary. A daily request
budget (`llm.daily_budget`, default 400 — well under Gemini's free-tier
~500/day/model cap) and a minimum interval between calls
(`llm.min_interval_seconds`) keep you inside the free tier. Whenever the key
is unset, the budget is spent, or a call fails, extraction falls back to
`src/listing_parser.py`'s regex/keyword heuristic automatically — a run
never hard-fails over this.

### Zone scoring

`config.yaml`'s `zone:` block scores listings by straight-line distance to a
single point you care about (a workplace, a landmark — defaults to
Dizengoff Square), in addition to (not instead of) the `search.neighborhoods`
keyword list: a listing within `zone.max_distance_meters` counts as a
location match even if its address text doesn't mention any of your
configured neighborhoods. Geocoding is free (OpenStreetMap Nominatim, no
key, cached to `data/geocode_cache.json` so nothing is looked up twice).
There's no walk-time/routing — just distance.

## Usage

```bash
python scripts/login_facebook_headless.py   # or login_facebook.py with a screen
python scripts/scan.py                      # pulls posts and checks for matches
python scripts/scan.py --dry-run            # classify and print, without writing/notifying
python scripts/matches.py                   # list everything matched so far, best score first
```

Re-run the login script whenever the session expires (Facebook logs you out
after a while of inactivity, or if it flags the login as suspicious). A scan
refuses to start a second time while one is already running (a lock file in
`data/scan.lock`), and stops cleanly instead of scraping garbage if Facebook
shows a checkpoint/login wall.

## Optional extras

### Telegram vote buttons

Each alert carries ⭐ Save / 🗑 Dismiss buttons. Saving nudges a listing's
score; dismissing hides it from `matches.py`/the dashboard without deleting
it. Handling taps needs a **separate, continuously-running** process (long-
polling isn't cron-friendly):

```bash
python scripts/bot_listener.py
```

Run it under a systemd service, a `tmux`/`screen` session, `pm2`, or
similar — whatever keeps a process alive on your machine. It needs nothing
beyond the same `TELEGRAM_BOT_TOKEN` already configured.

### Dashboard

```bash
python scripts/dashboard.py [--port 8765]
```

A local page (stdlib-only, no extra dependency) that reads `data/listings.db`
live and lists matches best-first, with the same Save/Dismiss actions. Every
route requires `?token=<DASHBOARD_TOKEN>` — there is no unauthenticated mode,
since listings carry addresses and phone numbers. Binds to `127.0.0.1` only:
**LAN/local-only by design, never expose this port to the internet.**

### Publishing a snapshot

```bash
python scripts/publish.py
```

Renders a static HTML snapshot and pushes it to a **dedicated** repo
(`SITE_REPO_URL`) for GitHub Pages, so you can check matches away from your
network. Read this before using it:

- **Create a separate repo for this** — never point `SITE_REPO_URL` at this
  code repo, or addresses/prices/phone numbers end up permanently in its
  public git history.
- **GitHub Pages on a public repo has no access control.** The published
  page carries a `noindex` hint (keeps it out of search engines), but
  anyone with the URL can open it. A private Pages site needs GitHub
  Pro/Enterprise. If that's not acceptable, use the [dashboard](#dashboard)
  instead and skip this.

### Google Sheets

Mirrors every matched listing into a shared Sheet you can sort/filter by
hand — additive to SQLite, disabled until set up.

1. In **Google Cloud Console**: create a project → enable the **Google
   Sheets API** → create a **service account** → download its JSON key.
2. Save that file as `auth/google_service_account.json` (the `auth/` folder
   is git-ignored — the key never gets committed).
3. Create a Google Sheet, open the JSON key and copy its `client_email`,
   then **share the sheet with that email as Editor**.
4. Copy the sheet's id from its URL
   (`docs.google.com/spreadsheets/d/`**`THIS_PART`**`/edit`) into `.env` as
   `GOOGLE_SHEET_ID`.

## Tests

```bash
pip install pytest ruff
pytest
ruff check .
```

Tests are all offline/pure-function — no live Facebook, Telegram, Gemini,
Nominatim, or Google Sheets calls, and they never touch `data/listings.db`
(each test that needs a database points `src.store` at a throwaway file).

## Important caveats

- **Facebook's Terms of Service prohibit automated scraping**, even of
  groups you belong to. This tool automates *your own* logged-in browser
  session for personal use, not bulk data collection or spam — but that's
  still a gray area under Facebook's ToS, and your account could be flagged
  or restricted. Use at your own risk, keep scan frequency low, and never
  leave it running unattended at scale. `src/scraper.py` jitters its delays
  and detects a checkpoint/login wall rather than scraping through it, but
  neither of those makes automated scraping compliant with Facebook's ToS —
  they only reduce how detectable and how damaging a scan is.
- Facebook's markup changes often and uses randomized class names, so the
  scraper in `src/scraper.py` relies on structural hints (`role="article"`,
  permalink patterns) that may need small tweaks over time if extraction
  stops finding posts.
- **The regex/keyword parser (`src/listing_parser.py`) is a fallback, not
  a language model** — used automatically whenever the LLM path isn't
  available. It will miss some genuine listings and occasionally flag a
  false positive; the address/phone fields it recovers in particular are
  best-effort. Tune `search.excluded_keywords` in your config to cut down
  on noise, or set `GEMINI_API_KEY` for meaningfully better extraction.
